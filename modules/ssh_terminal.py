import re
from typing import List

try:
    from ..models.server import ServerData
except ImportError:
    from models.server import ServerData

try:
    from .terminal_screen import TerminalScreen, DEFAULT_HISTORY_LINES
except ImportError:
    from modules.terminal_screen import TerminalScreen, DEFAULT_HISTORY_LINES

try:
    from .terminal_widget import TerminalWidget
except ImportError:
    from modules.terminal_widget import TerminalWidget

try:
    from .host_key_policy import SshKnownHostsPolicy
except ImportError:
    from modules.host_key_policy import SshKnownHostsPolicy

# v1.1.3 (ROADMAP tasks 1-2): the SFTP tab — a worker thread with a task queue and a UI.
try:
    from .sftp_worker import SftpWorker, register_orphan_sftp_worker
except ImportError:
    from modules.sftp_worker import SftpWorker, register_orphan_sftp_worker

try:
    from .sftp_tab import SftpTab, format_size
except ImportError:
    from modules.sftp_tab import SftpTab, format_size

# v1.2 (ROADMAP v1.2): the session was moved to a reusable page — the window
# became a thin wrapper. terminal_page does NOT import ssh_terminal at module
# level (it fetches it lazily via _st_module() — a test seam), so the cycle
# is excluded.
# v1.3.3.5 (ROADMAP v1.3.3.5): the terminal SPLIT — the window's session area is a
# vertical QSplitter [session_tabs | split_host] and the split host may hold a
# SECOND full session of the SAME node (a second shell over a second channel), so a
# TUI in the top pane and a usable command line below stop being mutually exclusive.
# The pane is an ordinary TerminalSessionPage (add_session(split=True)) — every
# concern of the split keeps its single owner (the PTY debounce, the idempotent
# page.shutdown(), the alternate screen per pyte screen, the multi-input provider).
try:
    from .terminal_page import TerminalSessionPage
except ImportError:
    from modules.terminal_page import TerminalSessionPage

# v1.2.9: Qt imports — only those actually used (QPlainTextEdit/QApplication and
# the other leftovers of the SSHTerminalTextEdit HTML path were removed along
# with the class).
# QMessageBox is NOT an HTML-path leftover — a live namespace for the test seams
# in terminal_page.py/terminal_dock.py: `_st_module().QMessageBox` is resolved
# at call time (the v1.1.4 host_attr pattern), so monkeypatching
# ST.QMessageBox.question/critical in tests works unchanged; without the import
# confirm_close("ask")/_show_error would crash with AttributeError
# (regression v1.2.9, caught by the suite).
# v1.3 (ROADMAP v1.3): the "Terminal Macros" panel — a command/script library to
# the left of the session tabs. command_library does not import ssh_terminal
# (no cycle).
try:
    from .command_library import CommandLibraryPanel
except ImportError:
    from modules.command_library import CommandLibraryPanel

from PySide6.QtCore import Qt, QThread, Signal, QEvent, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QMessageBox, QTabWidget, QProgressBar, QSplitter,
    QPushButton, QWidget, QVBoxLayout, QMenu,
)


# Pre-warmed translator for this module (loaded once on first call)
_t_cache = None

def get_translator():
    """Safe i18n helper — returns cached translator or fallback."""
    global _t_cache
    if _t_cache is None:
        try:
            from i18n import t as _func
            _t_cache = lambda key, **kwargs: (
                _func(key, **kwargs) if kwargs else _func(key)
            )
        except Exception:
            _t_cache = lambda k, **kw: f"[{k}]"
    return _t_cache


# ── v1.0 final (ROADMAP task 9): terminal_* keys from ~/.sshmap/config.json ────
# All keys are OPTIONAL, defaults = the current behaviour (a config without
# the keys looks exactly like RC4): palette "default", the system monospace
# pt 10, HistoryScreen depth DEFAULT_HISTORY_LINES=1000 (scrollback ON — the
# RC3 behaviour; an explicit 0 — the user deliberately disabled the scrollback),
# closing a session — immediately (v1.1: terminal_close_behavior). UI for the
# keys — v1.1 (the settings dialog); here they are read when the terminal
# window is created.
def load_terminal_settings():
    """Reads and validates the terminal_* keys from ~/.sshmap/config.json.

    Source — i18n.load_config() (never raises, {} on error). Returns:
      {"palette": str | None,     # None — not set; an unknown name → the window keeps "default"
       "font_family": str,        # "" — not set (system monospace)
       "font_size": int | None,   # None — not set (pt 10)
       "history_lines": int,      # HistoryScreen deque-history depth (0 = off)
       "close_behavior": str,     # v1.1: "close" (default) | "ask" — close behaviour
       "max_open": int,           # v1.1.1: limit of own open terminals (default 4)
       "wheel": str,              # v1.1.2RC3 (U3): "scrollback" (default) | "off" — the wheel
       "mode": str}               # v1.2.2: "windows" (default) | "tabs" — display mode
    Invalid values (a foreign type, out of range) → default. Never raises.
    """
    defaults = {"palette": None, "font_family": "", "font_size": None,
                "history_lines": DEFAULT_HISTORY_LINES, "close_behavior": "close",
                "max_open": 4, "wheel": "scrollback", "mode": "windows"}
    try:
        from i18n import load_config
    except Exception:
        return dict(defaults)
    cfg = load_config()

    v = cfg.get("terminal_palette")
    if isinstance(v, str) and v.strip():
        defaults["palette"] = v.strip()   # unknown name → set_palette() False → "default"

    v = cfg.get("terminal_font")
    if isinstance(v, str):
        defaults["font_family"] = v.strip()

    v = cfg.get("terminal_font_size")
    if isinstance(v, int) and not isinstance(v, bool) and 6 <= v <= 72:
        defaults["font_size"] = v         # out of range → pt 10 (default)

    v = cfg.get("terminal_history_lines")
    if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 1_000_000:
        defaults["history_lines"] = v     # negative/overflow → default 1000

    v = cfg.get("terminal_close_behavior")
    if isinstance(v, str) and v.strip().lower() in ("close", "ask"):
        defaults["close_behavior"] = v.strip().lower()  # corrupt/foreign → "close" (default)

    # v1.1.1 (ROADMAP item 3): limit of own open terminals — default 4;
    # when reached, MainWindow offers to close the oldest session instead of refusing.
    v = cfg.get("terminal_max_open")
    if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 32:
        defaults["max_open"] = v     # corrupt/out of range → 4 (default)

    # v1.1.2RC3 (AUDIT U3, leftover): mouse wheel — "scrollback" (default: the
    # wheel scrolls the local scrollback, as in v1.0RC3) | "off" (the wheel is
    # not intercepted for scrollback; full SGR wheel passthrough to the app —
    # v1.2+, since pyte 0.8.2 does not track the DECSET 1000/1002/1006 mouse
    # modes). The key is config-only (the ROADMAP v1.1.2RC3 decision — no UI in
    # the settings dialog).
    v = cfg.get("terminal_wheel")
    if isinstance(v, str) and v.strip().lower() in ("scrollback", "off"):
        defaults["wheel"] = v.strip().lower()   # corrupt/foreign → "scrollback" (default)

    # v1.2.2 (ROADMAP task 1): terminal display mode — "windows" (default,
    # current behaviour: separate SSHTerminalWindow windows) | "tabs"
    # (the "Terminals" QDockWidget in MainWindow, a QTabWidget of
    # TerminalSessionPage). Validation follows the pattern of the other keys:
    # a corrupt value / a foreign type → default.
    v = cfg.get("terminal_mode")
    if isinstance(v, str) and v.strip().lower() in ("windows", "tabs"):
        defaults["mode"] = v.strip().lower()   # corrupt/foreign → "windows" (default)

    return defaults


# ── v1.3.3.5 (ROADMAP v1.3.3.5): the terminal SPLIT ────────────────────────────
# The window's session area is a VERTICAL QSplitter: the session tabs on top and the
# split host (a SECOND full session of the SAME node) below. The state and the ratio
# live in ~/.sshmap/config.json — the ratio is a FRACTION of the height, so a window
# resize keeps the proportion; the pixel floor is derived from the canvas metrics
# (SPLIT_MIN_ROWS rows + the pane's own chrome), never from a magic number.
SPLIT_CONFIG_BOOL = "ui_terminal_split"          # bool — the pane was open at the last close
SPLIT_CONFIG_RATIO = "ui_terminal_split_ratio"   # float — the pane's share of the height
SPLIT_RATIO_DEFAULT = 0.25                       # the ROADMAP default (a quarter of the height)
SPLIT_RATIO_MIN = 0.10
SPLIT_RATIO_MAX = 0.75
SPLIT_MIN_ROWS = 4                               # the floor: 4 rows of the canvas (ROADMAP task 3a)


def load_split_settings():
    """v1.3.3.5 (ROADMAP task 5): the split state/ratio from ~/.sshmap/config.json.

    Source — i18n.load_config() (never raises, {} on error); all keys are optional and
    the defaults equal today's single-pane behaviour. Returns:
      {"split": bool,          # was the pane open at the last close (default False)
       "ratio": float}         # the pane's share of the height (default 0.25, clamped
                               # to SPLIT_RATIO_MIN..SPLIT_RATIO_MAX)
    A foreign type (a string "true", a bool where a float is expected, a non-finite
    number) → the default: a broken config must never open a second session or squeeze
    the panes into unusability. Never raises.
    """
    defaults = {"split": False, "ratio": SPLIT_RATIO_DEFAULT}
    try:
        from i18n import load_config
    except Exception:
        return dict(defaults)
    try:
        cfg = load_config()
    except Exception:  # noqa: BLE001 — a broken config store must not break the window
        return dict(defaults)

    v = cfg.get(SPLIT_CONFIG_BOOL)
    if isinstance(v, bool):
        defaults["split"] = v           # only a real JSON bool counts

    v = cfg.get(SPLIT_CONFIG_RATIO)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        try:
            ratio = float(v)
        except (TypeError, ValueError):
            ratio = SPLIT_RATIO_DEFAULT
        if ratio == ratio and ratio not in (float("inf"), float("-inf")):  # not NaN/inf
            defaults["ratio"] = max(SPLIT_RATIO_MIN, min(SPLIT_RATIO_MAX, ratio))
    return defaults


# ANSI escape sequences:
#   CSI (ESC [ ... final byte), simple escapes (ESC + char) and
#   OSC (ESC ] ... BEL | ESC \) — window-title-setting sequences that
#   TUI apps (vim/htop) send constantly. Without stripping them, the output
#   keeps garbage like "0;vim".
# v1.2.10rc2 (AUDIT manual #5a): used only by tests/test_core.py (in production
# pyte parses ANSI); DO NOT REMOVE — see ROADMAP "Do not touch".
ANSI_ESCAPE_RE = re.compile(
    r'\x1B\[[0-?]*[ -/]*[@-~]'   # CSI: ESC [ params final
    r'|\x1B\][^\x07\x1b]*(?:\x07|\x1B\\)'  # OSC: ESC ] ... BEL / ST
    r'|\x1B[@-_]'                # simple two-byte escapes
)


# ── v1.1.2RC1 (N4): orphan terminal thread registry ───────────────────────────
# The terminal window has WA_DeleteOnClose: if it is closed during a
# connection, closeEvent waits for the thread with just wait(1500), while
# paramiko can block for up to 15 s. The thread is created WITHOUT a QObject
# parent — with no strong referencing object, GC would destroy a LIVE QThread
# ("QThread: Destroyed while thread is still running" + the risk of a
# RuntimeError on late emits). The registry keeps such threads alive until
# finished() — the _active_workers pattern (modules/ssh_worker.py): all window
# slots are already disconnected in closeEvent, so late emits without
# receivers are a safe no-op.
_orphan_threads: List["SSHTerminalThread"] = []


def register_orphan_thread(thread: "SSHTerminalThread"):
    """Keep a still-running terminal thread alive until finished() (v1.1.2RC1, N4).

    Idempotent; self-cleans on the finished() signal.
    """
    if thread not in _orphan_threads:
        _orphan_threads.append(thread)

        def _drop(_=None, t=thread):
            try:
                _orphan_threads.remove(t)
            except ValueError:
                pass  # already removed (a double finished — does not happen in practice)
        thread.finished.connect(_drop)


class SSHTerminalThread(QThread):
    # v0.8.1: Signal(bytes), not str — recv() returns bytes, and PySide6 with
    # Signal(str) cannot convert bytes to QString ("Shiboken::Conversions:
    # Cannot copy-convert (bytes) to C++"); the slot received an empty string,
    # pyte saw nothing — the terminal "does not print". bytes ↔ QByteArray
    # converts natively.
    output_signal = Signal(bytes)
    error_signal = Signal(str)
    status_signal = Signal(str)
    closed_signal = Signal()
    # v1.0RC4: Quick Launch — emitted exactly once after invoke_shell, when the
    # channel is alive and ready to accept input (the window sends the first
    # command).
    connected_signal = Signal()

    def __init__(self, host, user, port, password="", key_path=""):
        super().__init__()
        self.host = host
        self.user = user
        self.port = port
        self.password = password
        self.key_path = key_path
        self.client = None
        self.channel = None
        self.running = True

    def run(self):
        import paramiko
        t = get_translator()

        try:
            self.status_signal.emit(t("terminal.connecting", user=self.user, host=self.host, port=self.port))

            # AUDIT v0.7.2 (high #4): known_hosts pinning instead of AutoAddPolicy
            client = paramiko.SSHClient()
            policy = SshKnownHostsPolicy(hostname=self.host, port=self.port)
            policy.apply_to_client(client)

            if self.key_path:
                client.connect(
                    self.host,
                    username=self.user,
                    port=self.port,
                    key_filename=self.key_path,
                    timeout=15,
                    look_for_keys=False,
                    allow_agent=True,
                )
            elif self.password:
                client.connect(
                    self.host,
                    username=self.user,
                    password=self.password,
                    port=self.port,
                    timeout=15,
                    look_for_keys=False,
                    allow_agent=False,
                )
            else:
                client.connect(
                    self.host,
                    username=self.user,
                    port=self.port,
                    timeout=15,
                    look_for_keys=True,
                    allow_agent=True,
                )

            self.client = client
            self.channel = client.invoke_shell(term='xterm', width=120, height=32)
            self.channel.settimeout(0.2)
            # v1.0RC4: channel ready — the window may send the first command (Quick Launch)
            self.connected_signal.emit()
            self.status_signal.emit(t("terminal.session_opened"))

            # AUDIT v0.7.2 (high #4): first connection — show the accepted fingerprint
            if policy.accepted_new_key and policy.last_fingerprint:
                note = t("ssh.host_key_new", host=self.host, fp=policy.last_fingerprint)
                self.status_signal.emit(note if not note.startswith("[")
                                        else f"New host key accepted ({policy.last_fingerprint})")

            while self.running and self.channel and not self.channel.closed:
                try:
                    if self.channel.recv_ready():
                        # v0.8: raw bytes with no ANSI stripping — pyte (TerminalScreen) parses them
                        data = self.channel.recv(4096)
                        if data:
                            self.output_signal.emit(data)
                    else:
                        self.msleep(30)
                except TimeoutError:
                    continue
                except Exception as recv_error:
                    if self.running:
                        self.error_signal.emit(str(recv_error))
                    break

        except paramiko.BadHostKeyException as e:
            # AUDIT v0.7.2 (high #4): the stored host key changed — a likely MITM
            try:
                from modules.logger import get_logger as _gl
                _gl("modules.ssh_terminal").warning(f"Host key mismatch for {self.host}: {e}")
            except Exception:
                pass
            msg = t("ssh.host_key_changed", host=self.host) + "\n" + str(e)
            # v1.1.2RC1 (N4): guard like in the recv loop — the window may have
            # closed during the connection (stop() → running=False); a late emit
            # without receivers is not needed.
            if self.running:
                self.error_signal.emit(msg if not msg.startswith("[") else f"Host key changed for {self.host}: {e}")
        except Exception as e:
            # v1.1.2RC1 (N4): guard like in the recv loop — see above.
            if self.running:
                self.error_signal.emit(str(e))
        finally:
            self.running = False
            if self.channel:
                try:
                    self.channel.close()
                except Exception:
                    pass
            if self.client:
                try:
                    self.client.close()
                except Exception:
                    pass
            self.closed_signal.emit()

    def send_data(self, data_bytes):
        if not data_bytes:
            return
        if self.channel and not self.channel.closed:
            try:
                self.channel.send(data_bytes)
            except Exception as e:
                self.error_signal.emit(str(e))

    def stop(self):
        self.running = False


# v1.2.9 (ROADMAP "Terminal hygiene"): the deprecated SSHTerminalTextEdit (the
# QPlainTextEdit HTML path, v1.0RC1) is REMOVED — dead code since v1.0RC1, never
# created by the window; keyboard handling lives in TerminalWidget.keyPressEvent.


class SSHTerminalWindow(QMainWindow):
    """v1.2.1 (ROADMAP v1.2.1): a terminal window with a QTabWidget of sessions.

    Each tab is one TerminalSessionPage (modules/terminal_page.py): an SSH
    session (thread + pyte screen + canvas + status line + SFTP tab). A new
    session = a new tab via the existing "connect to the node" path
    (MainWindow._spawn_terminal_window): if the node already has a live terminal
    window, the session opens there as a new tab; otherwise a new window with a
    single tab is created. The tab title is the node alias.

    Kept on the window: WA_DeleteOnClose, the title, geometry save/restore
    (modules/window_geometry.py, key ui_window_geometry_terminal) and the status
    bar with the SFTP progress bar — a bridge of the ACTIVE tab's signals
    (sticky text + progress; when switching tabs the bridge is reconnected —
    the v1.1.x look). The session state and ALL cleanup logic live on the page:
    teardown goes through the SINGLE page.shutdown() method, the "ask" gate —
    page.confirm_close(). Closing a tab = the page's existing cleanup logic
    (close_page); closing the LAST tab closes the window (WA_DeleteOnClose —
    current behaviour).

    v1.2 compatibility: session attributes are available on the window as live
    properties of the active tab (self.widget is self.page.widget etc.) — existing
    code/tests reading them via the window work unchanged.

    v1.3.3.5 (ROADMAP v1.3.3.5): the session area is a VERTICAL splitter
    [session_tabs | split_host] — the ONE checkable action `act_split`
    (`terminal.split`, the BUTTON in the right corner of the tab bar + the window's
    context-menu item) opens a
    SECOND full session of the same node in the host under the tabs (default 25% of
    the height). The host is hidden while the split is off (a hidden splitter member
    costs no geometry — the single-pane look is unchanged), the pane is an ordinary
    page created through add_session(split=True) and therefore carries the same
    set_host_window()/close_page()/shutdown() contract — except that a pane is built
    WITHOUT the SFTP tab (it is a command line: `with_sftp=False` in §14b). The pane
    is NOT a tab: it is
    marked `_is_split_pane` (the terminal_max_open limit and
    _find_terminal_window_for skip it, while the green dot and the multi-input
    provider still count it — ui/main_window_ssh.py).
    """

    def __init__(self, server_data: ServerData, parent=None, password: str = None,
                 initial_command: str = ""):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        # BUGFIX v0.9.5.5 (kept): server_data on the window is a compat attribute
        # (the data of the FIRST session; the window hosts sessions of one node);
        # since v1.2 the MainWindow tracking reads it from the SESSION
        # (page.server_data).
        self.server_data = server_data

        # v1.3.3.5: the split state — BEFORE the layout (add_session() below may ask
        # for the restore and the page property reads the pane).
        self._split_pane = None
        self._split_on = False
        self._split_config = load_split_settings()
        self._split_ratio = self._split_config["ratio"]

        t = get_translator()
        self.setWindowTitle(t("terminal.window_title", alias=server_data.alias, host=server_data.host))
        # v1.2.3 (ROADMAP task 2): the base title for the multi-input mode highlight —
        # apply_container_highlight swaps in/removes the terminal.multi_title_prefix prefix.
        self._multi_base_title = self.windowTitle()
        self.resize(800, 600)

        # v1.1.2RC3 (AUDIT U2): restore the size/state of the previous terminal
        # window from config.json (saved in closeEvent). All terminal windows
        # share the single key ui_window_geometry_terminal — the last closed one
        # is remembered; no key / a corrupt value → the default 800×600 above.
        try:
            from .window_geometry import restore_window_geometry as _restore_geo
        except ImportError:
            from modules.window_geometry import restore_window_geometry as _restore_geo
        _restore_geo("ui_window_geometry_terminal", self)

        # v1.2.1 (task 1): the session tabs — a QTabWidget of session pages
        # (each tab = one SSH session). The tabs are closable: closing a tab =
        # the page's existing cleanup logic; the last tab → the window's close().
        self.session_tabs = QTabWidget()
        self.session_tabs.setTabsClosable(True)
        self.session_tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        self.session_tabs.currentChanged.connect(self._on_current_tab_changed)

        # v1.3.3.5 (ROADMAP task 1): the SPLIT — the session area becomes a VERTICAL
        # QSplitter [session_tabs | split_host]; the host holds the second session and
        # is HIDDEN until the split is on (a hidden splitter member costs no geometry,
        # so the single-pane look of v1.3.3.4 is preserved). NOT collapsible on either
        # side (the divider can never "lose" a pane) and the floors are applied with
        # setMinimumHeight + setSizes only (Qt gotcha #13: setMaximum* on a splitter
        # member breaks the size accounting after hide/show).
        self.split_host = QWidget()
        _split_layout = QVBoxLayout(self.split_host)
        _split_layout.setContentsMargins(0, 0, 0, 0)
        _split_layout.setSpacing(0)
        self._v_splitter = QSplitter(Qt.Orientation.Vertical)
        self._v_splitter.addWidget(self.session_tabs)
        self._v_splitter.addWidget(self.split_host)
        self._v_splitter.setCollapsible(0, False)
        self._v_splitter.setCollapsible(1, False)
        self._v_splitter.splitterMoved.connect(self._on_split_moved)
        self.split_host.hide()

        # v1.3 (ROADMAP v1.3): the "Terminal Macros" panel to the left of the
        # session tabs — QSplitter [cmdlib_panel | QSplitter(session_tabs | split_host)].
        # A double-click/Enter on a command — sends the macro to the ACTIVE session (not
        # the multi-input broadcast; v1.3.3.5: the panel asks the container for the
        # session the user is in, so a macro lands in the FOCUSED pane). Collapsing into
        # a thin strip (the v1.2.4.1 technique) — the state lives in the single config
        # key ui_cmdlib_collapsed for both containers (window + dock).
        # setCollapsible(False) on both sides: the panel cannot be "lost" by dragging
        # the splitter. The panel's status messages go to the existing
        # _on_page_status_message → statusBar() bridge (the same (str, int) signature,
        # no new bridge code).
        self.cmdlib_panel = CommandLibraryPanel(self.session_tabs, parent=self)
        self.cmdlib_panel.status_message.connect(self._on_page_status_message)
        self.cmdlib_panel.set_active_session_provider(self.active_session)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.cmdlib_panel)
        splitter.addWidget(self._v_splitter)
        # setCollapsible AFTER addWidget (Qt: an out-of-range index otherwise):
        # the panel cannot be "lost" by dragging the splitter to zero.
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        self.setCentralWidget(splitter)

        # v1.3.3.5 (ROADMAP task 1): ONE checkable action drives BOTH surfaces — the
        # BUTTON in the right corner of the session tab bar and the window's
        # context-menu item (`terminal.split`). No registry sequence: a keyboard
        # shortcut is deliberately NOT part of this version (ROADMAP "Not in
        # v1.3.3.5"), so the action ships without one.
        # The button is a plain QPushButton — the look of the command panel's
        # Add/Edit/Delete buttons (a toolbar item read as a label, not as a control).
        # A QPushButton has no setDefaultAction in PySide6, so it is wired to the
        # action by hand (`clicked` → the action; the action's state → the button):
        # the ACTION stays the single source of truth, and `retranslate()` re-texts
        # both from the same key.
        self.act_split = QAction(t("terminal.split"), self)
        self.act_split.setCheckable(True)
        self.act_split.setToolTip(t("terminal.split_tooltip"))
        self.act_split.toggled.connect(self._sync_split_button)
        self.act_split.toggled.connect(self.set_split_enabled)
        self.btn_split = QPushButton(t("terminal.split"))
        self.btn_split.setCheckable(True)
        self.btn_split.setToolTip(t("terminal.split_tooltip"))
        self.btn_split.clicked.connect(self._on_split_button_clicked)
        # The right corner of the session tab bar: the natural place of a per-session
        # action (the left side belongs to the command panel).
        self.session_tabs.setCornerWidget(self.btn_split, Qt.Corner.TopRightCorner)

        # v1.2 (`windows` mode): the "status bar" is bridged into the window's status
        # bar — sticky text + SFTP progress (a permanent widget on the right, hidden
        # when there are no transfers) exactly as in v1.1.x; since v1.2.1 only the
        # ACTIVE tab is bridged (_set_bridged_page); v1.3.3.5: the FOCUSED pane wins.
        # The page does not know about QMainWindow: in dock mode (v1.2.2) the bridge
        # will attach to the dock.
        self._sftp_progress = QProgressBar()
        self._sftp_progress.setFixedWidth(180)
        self._sftp_progress.setTextVisible(True)
        self._sftp_progress.setVisible(False)
        self.statusBar().addPermanentWidget(self._sftp_progress)
        self._bridged_page = None

        # v1.3.3.5 (ROADMAP task 6): the bridge follows the FOCUSED session. The
        # application-level focusChanged signal is the reliable trigger (see
        # _wire_page); PySide6 drops the connection together with this QObject.
        try:
            _app = QApplication.instance()
            if _app is not None:
                _app.focusChanged.connect(self._on_app_focus_changed)
        except Exception:  # noqa: BLE001 — a window without an application (a unit test)
            pass

        # The first session — via the same path as a new tab (v1.2.1 task 1).
        self.add_session(server_data, password=password, initial_command=initial_command)

        # v1.3.3.5 (ROADMAP task 5): the RESTORED split state — through the ONE action
        # (toggled → set_split_enabled), so the button, the pane and the geometry can
        # never diverge. The registry hook of the host (the MainWindow) is looked up on
        # the PARENT at that moment — see _session_sink().
        if self._split_config["split"]:
            self.act_split.setChecked(True)

    # ── v1.3.3.1 (ROADMAP task 1): live i18n — re-text on a language switch ──

    def retranslate(self):
        """v1.3.3.1: re-text the window and its sessions in the current language.

        The window title (`terminal.window_title`), the close tooltip of every tab
        (`terminal.tab_close_tooltip`) and — through each page — the `Terminal | Files`
        titles, the SFTP buttons/headers and the command-library panel. Every string
        already has an i18n key (ZERO new keys); the module translator is looked up at
        call time, so its cache needs no invalidation.

        The multi-input title prefix is PRESERVED: while the mode is on the title is
        `terminal.multi_title_prefix + base` (the base is rebuilt here and re-prefixed),
        otherwise the plain base title is restored. Never raises — the dead-C++-object
        discipline of every container method.
        """
        t = get_translator()
        data = getattr(self, "server_data", None)
        base = t("terminal.window_title",
                 alias=getattr(data, "alias", "?"), host=getattr(data, "host", ""))
        # v1.2.3: the multi-input prefix lives on the window title (multi_input.py);
        # the base is recomputed here, so the prefix is re-added instead of lost.
        prefixed = False
        try:
            from .multi_input import get_hub as _get_hub
        except ImportError:  # flat launch from the project root
            try:
                from multi_input import get_hub as _get_hub
            except ImportError:
                _get_hub = None
        if _get_hub is not None:
            try:
                prefixed = bool(_get_hub().active)
            except Exception:  # noqa: BLE001 — the hub must not break the re-text
                prefixed = False
        self._multi_base_title = base
        try:
            self.setWindowTitle((t("terminal.multi_title_prefix") + base) if prefixed else base)
        except RuntimeError:
            return  # the C++ object was already destroyed (a close race)
        # v1.3.3.5: the split action (the tab-bar BUTTON and the context-menu item) —
        # one label, one tooltip, two views.
        act = getattr(self, "act_split", None)
        if act is not None:
            try:
                act.setText(t("terminal.split"))
                act.setToolTip(t("terminal.split_tooltip"))
            except RuntimeError:
                pass  # Qt teardown — the action is already destroyed
        btn = getattr(self, "btn_split", None)
        if btn is not None:
            try:
                btn.setText(t("terminal.split"))
                btn.setToolTip(t("terminal.split_tooltip"))
            except RuntimeError:
                pass  # Qt teardown — the button is already destroyed
        try:
            for i in range(self.session_tabs.count()):
                self.session_tabs.setTabToolTip(i, t("terminal.tab_close_tooltip"))
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)
        # v1.3.3.5: EVERY live session — the tabs AND the split pane (a page re-texts
        # its own [Terminal | Files] titles; the pane re-applies its multi-input badge).
        pages = self._all_pages()
        for page in pages:
            try:
                page.retranslate()
            except RuntimeError:
                pass  # Qt teardown — the page is already destroyed
        # v1.3.3.1: the "Terminal macros" panel belongs to the CONTAINER (both the
        # window and the dock own one), so it is re-texted here — not by the page.
        cmdlib = getattr(self, "cmdlib_panel", None)
        if cmdlib is not None:
            try:
                cmdlib.retranslate()
            except RuntimeError:
                pass  # Qt teardown — the panel is already destroyed

    # ── v1.4.3 (ROADMAP task 4): live theme — the container and its sessions ──

    def refresh_theme(self):
        """v1.4.3: re-apply the theme to the window and every live session.

        The twin of `retranslate()` (the same registry, the same dead-C++-object
        discipline): the window owns the container, and each `TerminalSessionPage`
        re-applies its status line, its canvas's floating find panel and its SFTP
        tab. The terminal's own OUTPUT palette is deliberately out of scope
        (AGENTS.md §4.6). Never raises.
        """
        try:
            pages = self._all_pages()
        except Exception:  # noqa: BLE001 — a broken registry must not break the switch
            pages = []
        for page in pages:
            hook = getattr(page, "refresh_theme", None)
            if not callable(hook):
                continue
            try:
                hook()
            except RuntimeError:
                continue  # Qt teardown — the page is already destroyed
            except Exception:  # noqa: BLE001 — one session must not stop the rest
                continue
        cmdlib = getattr(self, "cmdlib_panel", None)
        if cmdlib is not None:
            hook = getattr(cmdlib, "refresh_theme", None)
            if callable(hook):
                try:
                    hook()
                except RuntimeError:
                    pass  # Qt teardown — the panel is already destroyed
        try:
            self.update()
        except RuntimeError:
            pass

    # ── v1.2.1: tabs = sessions ──────────────────────────────────────────────

    def add_session(self, server_data: ServerData, password: str = None,
                    initial_command: str = "", split: bool = False) -> "TerminalSessionPage":
        """v1.2.1 (task 1): a new session = a new tab (the existing
        "connect to the node" path). The page is created with parent=session_tabs
        (destroyed together with the window), bound to the host and added as a tab —
        title: the node alias, tooltip: terminal.tab_close_tooltip. The new tab
        becomes active (setCurrentIndex → currentChanged → the signal bridge to the
        status bar).

        v1.3.3.5 (ROADMAP task 1): `split=True` — the SPLIT PANE instead of a tab: the
        page is created in the split host (the same TerminalSessionPage, the same
        set_host_window()/close_page()/shutdown() contract), it carries the
        `_is_split_pane` marker (the terminal_max_open limit and
        _find_terminal_window_for skip it — ui/main_window_ssh.py) and it does NOT
        become the active tab (it is not a tab at all). The caller — the ONE split
        action — shows the host.
        """
        t = get_translator()
        if split:
            # v1.3.3.5: the pane is a COMMAND LINE — no SFTP tab (a second channel, a
            # second worker and a file tree squeezed into ~130 px are pure cost there);
            # it also keeps the page's own layout minimum small, which is what makes the
            # 25% default honest (the pane's floor is then driven by the canvas rows).
            # And no STATUS LINE either (`with_status_line=False`): the pane's live state
            # goes onto its inner `Terminal` tab ("Terminal  SSH session opened") instead
            # of a whole row under the canvas — measured, that row plus its spacing costs
            # ~25 px of a ~140 px pane.
            page = TerminalSessionPage(
                server_data, parent=self.split_host, with_sftp=False,
                with_status_line=False,
                password=password, initial_command=initial_command)
            page.set_host_window(self)
            page._is_split_pane = True
            self._wire_page(page)
            try:
                self.split_host.layout().addWidget(page)
            except (RuntimeError, AttributeError):
                pass  # the host was already destroyed (a close race) — the page lives on
            return page
        page = TerminalSessionPage(
            server_data, parent=self.session_tabs,
            password=password, initial_command=initial_command)
        page.set_host_window(self)
        self._wire_page(page)
        idx = self.session_tabs.addTab(page, server_data.alias)
        # Qt: addTab makes only the FIRST tab current — activate the new one
        # explicitly (currentChanged → the signal bridge to the status bar).
        self.session_tabs.setCurrentIndex(idx)
        try:
            self.session_tabs.setTabToolTip(idx, t("terminal.tab_close_tooltip"))
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race) — the tooltip is not critical
        return page

    def close_page(self, page):
        """v1.2.1 (task 2): close ONE tab — the page's existing cleanup logic
        (the "ask" gate confirm_close → the single shutdown teardown); the
        neighbouring tabs are not touched. Closing the LAST tab closes the window
        (WA_DeleteOnClose — current behaviour).

        v1.3.3.5: the SPLIT PANE has no tab, so its own close paths (the session error
        → page.close_terminal() → here, the MainWindow shutdown) are routed to the
        split teardown through the ONE action; the window itself is never closed by a
        pane (closing the window stays the user's action).
        """
        idx = self.session_tabs.indexOf(page)
        if idx < 0:
            if page is getattr(self, "_split_pane", None):
                self.set_split_enabled(False)
            return  # the tab was already removed (a teardown race)
        try:
            if not page.confirm_close():
                return  # "ask" + Cancel — the tab stays open
        except RuntimeError:
            pass  # the C++ object was already destroyed — close without asking (as before)
        try:
            page.shutdown()
        except Exception:  # noqa: BLE001 — teardown robustness
            pass
        self.session_tabs.removeTab(idx)   # currentChanged → the bridge reconnects
        page.deleteLater()
        if self.session_tabs.count() == 0:
            self.close()  # the last tab — close the window (WA_DeleteOnClose)

    def _on_tab_close_requested(self, index: int):
        """The tab's close cross (setTabsClosable) → close_page."""
        try:
            page = self.session_tabs.widget(index)
        except RuntimeError:
            return  # the C++ object was already destroyed (a close race)
        if page is not None:
            self.close_page(page)

    # ── v1.3.3.5 (ROADMAP v1.3.3.5): the SPLIT — a second pane under the sessions ──
    #
    # The whole feature hangs on ONE owner per concern:
    #   * the ACTION (`act_split`, `terminal.split`) — the tab-bar BUTTON and the
    #     window's context-menu item are views of the same checkable QAction, so the
    #     checkmark, the pane and the geometry can never diverge;
    #   * the LAYOUT — the vertical QSplitter [session_tabs | split_host]; the host is
    #     hidden while the split is off, so the single-pane look costs nothing;
    #   * the SESSION — an ordinary TerminalSessionPage (add_session(split=True)): its
    #     own SSHTerminalThread to the SAME node, its own pyte screen (a TUI in EACH
    #     pane is legal by construction), its own PTY debounce and the idempotent
    #     page.shutdown() of every other teardown path;
    #   * the REGISTRY — the pane is a real session for the green dot and the
    #     multi-input provider, but NOT a reason to refuse a new terminal: the page
    #     marker `_is_split_pane` keeps it out of the terminal_max_open limit
    #     (ui/main_window_ssh.py; the window registers the pane through the host's
    #     duck-typed `_adopt_split_session`);
    #   * the PERSISTENCE (~/.sshmap/config.json) — `ui_terminal_split` +
    #     `ui_terminal_split_ratio`, merged into the window's geometry write.

    @property
    def split_pane(self):
        """v1.3.3.5: the live split pane (None while the split is off).

        The container exposes it for the multi-input highlight
        (modules/multi_input.py walks the session tabs and reaches the pane here).
        """
        return getattr(self, "_split_pane", None)

    def active_session(self):
        """v1.3.3.5 (ROADMAP task 6): the session the USER is working in — the focused
        split pane when the keyboard focus is inside it, otherwise the ACTIVE tab (the
        v1.2.1 rule). The command library asks the container for it, so a macro lands
        in the pane the user clicked — the "send to the active session" promise is
        extended to the pane instead of a second concept being introduced.
        """
        return self.page

    def focused_split_pane(self):
        """v1.3.3.5 (ROADMAP task 6): the split pane while the focus is INSIDE it.

        `QApplication.focusWidget()` is the single source of truth (the canvas of a
        pane that the user clicked has it; `hasFocus()` on the pane itself would not
        see its children). RuntimeError on a dead C++ object → None (teardown).
        """
        pane = getattr(self, "_split_pane", None)
        if pane is None:
            return None
        try:
            focus = QApplication.focusWidget()
        except RuntimeError:
            return None
        if focus is None:
            return None
        try:
            if focus is pane or pane.isAncestorOf(focus):
                return pane
        except RuntimeError:
            return None
        return None

    def set_split_enabled(self, on: bool):
        """v1.3.3.5 (ROADMAP tasks 1/2/3): the ONE split action — on/off.

        ON — the pane is created (a REAL second session of the same node: a fresh
        SSHTerminalThread with the parent's credentials, WITHOUT the parent's Quick
        Launch command and WITHOUT forcing the SFTP worker), the host is shown and the
        sizes come from the stored ratio (default 0.25 of the height).
        OFF — the "ask" gate of the pane (`page.confirm_close()`, the SAME gate every
        other session close uses) and the single teardown `page.shutdown()`; a Cancel
        leaves the pane open and puts the checkmark back without re-entering this slot.
        Called from `act_split.toggled` and from close_page (a pane's own close path).
        """
        on = bool(on)
        if on == self._split_on:
            # an internal path (the pane's own close/error) already moved the state —
            # only the checkmark has to catch up (blocked signals, no recursion)
            self._set_split_action_checked(on)
            return
        if on:
            self._open_split_pane()
            if self._split_pane is None:
                self._split_on = False
                self._set_split_action_checked(False)
                return   # the pane could not be created — the checkmark goes back
        else:
            if not self._close_split_pane():
                self._set_split_action_checked(True)
                return  # the "ask" gate was cancelled — the pane stays
        self._split_on = on
        self._set_split_action_checked(on)

    def _open_split_pane(self):
        """Create and show the split pane (idempotent — already open ⇒ no-op)."""
        if self._split_pane is not None:
            return
        pane = self.add_session(
            self._split_server_data(),
            password=self._split_password(),
            initial_command="",   # the parent's Quick Launch is NOT re-sent (ROADMAP task 4)
            split=True)
        self._split_pane = pane
        self._split_on = True   # BEFORE show(): the resize events of the layout arrive first
        try:
            self.split_host.show()
        except RuntimeError:
            return  # C++ teardown — nothing to show
        self._apply_split_sizes()
        # the layout of a just-shown pane settles after the event cycle (the page's own
        # singleShot(0) grid sync is the same pattern) — a second pass on the real size.
        try:
            QTimer.singleShot(0, self._apply_split_sizes)
        except RuntimeError:
            pass  # teardown race — the immediate pass above already ran
        self._register_split_session(pane)
        # v1.3.3.5: the new pane's canvas takes the focus (TerminalSessionPage.__init__)
        # — the bridge follows it right away (no FocusIn event is guaranteed).
        self._refresh_bridge()

    def _close_split_pane(self) -> bool:
        """Tear the pane down; False — the "ask" gate was cancelled (the pane stays)."""
        pane = getattr(self, "_split_pane", None)
        if pane is None:
            self.split_host.hide()
            self._split_on = False
            return True
        try:
            if not pane.confirm_close():
                return False
        except RuntimeError:
            pass  # C++ teardown — close without asking (as everywhere else)
        try:
            pane.shutdown()
        except Exception:  # noqa: BLE001 — teardown robustness
            pass
        self._split_pane = None
        self._split_on = False
        self._reset_split_floors(pane)
        try:
            self.split_host.layout().removeWidget(pane)
        except (RuntimeError, AttributeError):
            pass  # the host was already destroyed (a close race)
        try:
            pane.setParent(None)
            pane.deleteLater()
        except RuntimeError:
            pass  # teardown race — the page dies with its parent anyway
        try:
            self.split_host.hide()
        except RuntimeError:
            pass
        # the bridge returns to the ACTIVE tab (the pane it pointed at is gone)
        self._refresh_bridge()
        return True

    def _wire_page(self, page):
        """v1.3.3.5 (ROADMAP task 6): let the window follow the FOCUS of a canvas.

        The bridge and `win.page` used to follow the ACTIVE TAB only (v1.2.1); with a
        split there are two sessions on the screen at once, so the container follows
        the focus as well. The canvas FocusIn filter is the cheap first half — the
        reliable half is the application-level `focusChanged` signal connected in
        __init__: a page's canvas calls `setFocus()` while it is still hidden
        (`TerminalSessionPage.__init__`), so the pane can hold the focus WITHOUT any
        FocusIn event ever reaching this window (verified offscreen and on Windows).
        Never raises.
        """
        try:
            page.widget.installEventFilter(self)
        except (RuntimeError, AttributeError):
            pass  # a test double without a canvas / a dead C++ object

    def eventFilter(self, obj, event):
        """v1.3.3.5 (ROADMAP task 6): a canvas FocusIn re-points the status-bar bridge
        (and therefore `win.page`) at the session the user just clicked into."""
        if event.type() == QEvent.Type.FocusIn:
            self._refresh_bridge()
        return super().eventFilter(obj, event)

    def _on_app_focus_changed(self, _old=None, _now=None):
        """v1.3.3.5: the application focus moved anywhere — re-point the bridge.

        Idempotent and cheap (`_set_bridged_page` returns immediately when the page did
        not change), so the signal may be connected once per terminal window without
        guarding for ancestry first.
        """
        self._refresh_bridge()

    def _refresh_bridge(self):
        """v1.3.3.5 (ROADMAP task 6): the bridge target — the FOCUSED pane if the
        keyboard focus is inside it, otherwise the ACTIVE tab (the v1.2.1 rule)."""
        pane = self.focused_split_pane()
        if pane is not None:
            self._set_bridged_page(pane)
            return
        try:
            cur = self.session_tabs.currentWidget()
        except RuntimeError:
            cur = None  # the C++ object was already destroyed (a close race)
        self._set_bridged_page(cur)

    def _all_pages(self) -> list:
        """v1.3.3.5: EVERY live session of this window — the tabs AND the split pane.

        Single source for the teardown (closeEvent), the re-text (retranslate) and the
        focus lookup: a pane must never be missed by a loop over `session_tabs`.
        """
        try:
            pages = [self.session_tabs.widget(i) for i in range(self.session_tabs.count())]
        except RuntimeError:
            pages = []  # the C++ object was already destroyed (a close race)
        pane = getattr(self, "_split_pane", None)
        if pane is not None:
            pages.append(pane)
        return [p for p in pages if p is not None]

    def _split_server_data(self):
        """The node of the pane — the ACTIVE tab's data (fallback: the window's)."""
        try:
            page = self.session_tabs.currentWidget()
        except RuntimeError:
            page = None
        data = getattr(page, "server_data", None)
        return data if data is not None else self.server_data

    def _split_password(self):
        """The credentials of the pane — the SAME node, the SAME password as the parent
        session (the explicit one the window was created with is kept on the thread;
        the model itself never carries it, AUDIT v0.7.2 medium #7)."""
        try:
            page = self.session_tabs.currentWidget()
            thread = getattr(page, "terminal_thread", None)
            return getattr(thread, "password", "") or ""
        except RuntimeError:
            return ""

    def _session_sink(self):
        """v1.3.3.5 (ROADMAP task 2): the host's session-registry hook.

        The pane is a real session (green dot, multi-input) that was NOT created by
        `SshMixin._spawn_terminal_window`, so it must reach `MainWindow._terminal_windows`
        through the host. The hook is duck-typed on the PARENT of the window (the
        MainWindow in `terminal_mode = "windows"`) — no import of ui.main_window from
        modules/* (the cycle rule) and no extra constructor argument (a test window may
        be created with parent=None: the pane then simply lives and dies with it).
        """
        try:
            host = self.parent()
        except RuntimeError:
            return None
        fn = getattr(host, "_adopt_split_session", None)
        return fn if callable(fn) else None

    def _register_split_session(self, page):
        """Hand the pane to the host registry (a no-op without a host — see above)."""
        sink = self._session_sink()
        if sink is None:
            return
        try:
            sink(page)
        except Exception:  # noqa: BLE001 — the registry must never break the split
            pass

    def _set_split_action_checked(self, checked: bool):
        """Set the action's checkmark (and the BUTTON mirroring it) WITHOUT re-entering
        the slot — the "ask" gate of the pane: a Cancel must leave the pane open and the
        control pressed."""
        checked = bool(checked)
        act = getattr(self, "act_split", None)
        if act is not None:
            try:
                act.blockSignals(True)
                act.setChecked(checked)
                act.blockSignals(False)
            except RuntimeError:
                pass  # teardown — the action is gone
        self._sync_split_button(checked)

    def _sync_split_button(self, checked=None):
        """Keep the corner BUTTON in step with the ONE action.

        A QPushButton has no `setDefaultAction` in PySide6, so the mirror is explicit:
        the action's `toggled` is the source and this slot (plus
        `_set_split_action_checked`, where the action's signals are blocked) writes the
        button's state. Idempotent and teardown-safe — never raises.
        """
        btn = getattr(self, "btn_split", None)
        act = getattr(self, "act_split", None)
        if btn is None or act is None:
            return
        try:
            if checked is None:
                checked = bool(act.isChecked())
            btn.blockSignals(True)
            btn.setChecked(bool(checked))
            btn.blockSignals(False)
        except RuntimeError:
            pass  # teardown — the button is gone

    def _on_split_button_clicked(self, _checked=False):
        """The BUTTON asks the ACTION (one source of truth): the click does not change
        the state itself — `set_split_enabled()` does, through the action's `toggled`."""
        act = getattr(self, "act_split", None)
        btn = getattr(self, "btn_split", None)
        if act is None or btn is None:
            return
        try:
            act.setChecked(bool(btn.isChecked()))
        except RuntimeError:
            pass  # teardown — the action is gone

    def _split_min_height(self) -> int:
        """v1.3.3.5 (ROADMAP task 3a): the size floor of the bottom pane, in PIXELS.

        The floor is BUILT, not guessed: the canvas of the pane gets a minimum height of
        `SPLIT_MIN_ROWS` rows measured from the live cell metrics (`widget.cell_size`,
        never a magic pixel number) and the pane's own CHROME is measured from the live
        geometry (`pane.height() - pane.widget.height()` — the status line, the
        `[Terminal | Files]` tab bar and the layout margins; before the first layout the
        hints of those two widgets are the fallback). The SFTP tab's own size hint is
        deliberately NOT the reference: it is a property of a tab the user may never
        open, and the ROADMAP fixes the floor at a few ROWS. The result is returned AND
        installed as an explicit `minimumHeight` on both panes by `_apply_split_sizes`
        (an explicit minimum overrides `minimumSizeHint` — that is what turns the floor
        into the splitter's own limit). Never raises.
        """
        pane = getattr(self, "_split_pane", None)
        if pane is None:
            return 0
        row_h = 16
        try:
            row_h = max(1, int(pane.widget.cell_size[1]))
        except (RuntimeError, AttributeError, TypeError, IndexError):
            row_h = 16   # a dying C++ object — a sane default for the single pass
        canvas_floor = int(row_h * SPLIT_MIN_ROWS)
        try:
            pane.widget.setMinimumHeight(canvas_floor)
        except (RuntimeError, AttributeError):
            pass  # C++ teardown — the splitter floor below is best-effort then
        chrome = 0
        try:
            chrome = int(pane.height()) - int(pane.widget.height())
        except (RuntimeError, TypeError):
            chrome = 0
        if chrome <= 0:
            try:
                chrome = int(pane.status_label.sizeHint().height()
                             + pane.tabs.tabBar().sizeHint().height()) + 24
            except (RuntimeError, AttributeError, TypeError):
                chrome = 0
        return canvas_floor + max(0, chrome)

    def _current_split_ratio(self):
        """The pane's CURRENT share of the splitter height (None — nothing to measure).

        None while the split is OFF (`_split_pane is None`) or while the host is hidden
        (its size is 0): a ratio measured on a hidden member would be 0 and would
        OVERWRITE the proportion the user left behind — the last real proportion (the
        value restored on the next window) is kept instead.
        """
        if getattr(self, "_split_pane", None) is None:
            return None
        try:
            sizes = self._v_splitter.sizes()
        except RuntimeError:
            return None
        if len(sizes) < 2:
            return None
        total = sum(sizes)
        if total <= 0 or sizes[1] <= 0:
            return None
        return sizes[1] / float(total)

    def _on_split_moved(self, _pos=None, _index=None):
        """v1.3.3.5 (ROADMAP task 3a): the user dragged the divider — the new
        proportion becomes THE ratio, so the next window resize keeps it (the explicit
        drag is respected; the clamp only guards the unusable extremes)."""
        ratio = self._current_split_ratio()
        if ratio is None:
            return
        self._split_ratio = max(SPLIT_RATIO_MIN, min(SPLIT_RATIO_MAX, ratio))

    def _apply_split_sizes(self):
        """v1.3.3.5 (ROADMAP task 3a): the two geometry answers of the split.

        (1) The pane is a FRACTION of the height (`_split_ratio`), so a window resize
            keeps the proportion — applied on open, on every resize and after the user
            drags the divider;
        (2) both panes get a FLOOR of a few rows (`_split_min_height`), so the divider
            can never collapse one of them into unusability — the floor is expressed as
            `setMinimumHeight` + `setSizes` (Qt gotcha #13 forbids `setMaximum*` on a
            splitter member). A window too short for two floors splits evenly instead of
            producing negative sizes. Never raises.
        """
        if getattr(self, "_split_pane", None) is None:
            return
        try:
            total = self._v_splitter.height() - self._v_splitter.handleWidth()
        except RuntimeError:
            return
        if total <= 0:
            return  # not laid out yet (the deferred pass / the resize will do it)
        floor = self._split_min_height()
        bottom = int(round(total * self._split_ratio))
        if total > 2 * floor:
            bottom = max(floor, min(bottom, total - floor))
        else:
            bottom = max(1, total // 2)   # too short for two floors — split evenly
        top = max(1, total - bottom)
        try:
            self.split_host.setMinimumHeight(floor)
            self.session_tabs.setMinimumHeight(floor)
            self._v_splitter.setSizes([top, bottom])
        except RuntimeError:
            pass  # C++ teardown — nothing to size

    def _reset_split_floors(self, pane=None):
        """Drop the floors of `_apply_split_sizes` with the pane (the single-pane
        look — and the window's minimum size — of v1.3.3.4 is restored exactly).

        `pane` is passed explicitly by `_close_split_pane` (there the pane is already
        detached from `self._split_pane`).
        """
        if pane is None:
            pane = getattr(self, "_split_pane", None)
        try:
            if pane is not None:
                pane.widget.setMinimumHeight(0)
        except (RuntimeError, AttributeError):
            pass  # C++ teardown — nothing to reset
        try:
            self.split_host.setMinimumHeight(0)
            self.session_tabs.setMinimumHeight(0)
        except RuntimeError:
            pass  # C++ teardown — nothing to reset

    def _save_split_state(self, extra: dict = None) -> dict:
        """v1.3.3.5 (ROADMAP task 5): the split state/ratio as CONFIG keys.

        Returns the extra top-level keys of the geometry write (`ui_terminal_split` +
        `ui_terminal_split_ratio`, the ratio re-read from the live splitter and
        clamped), so `closeEvent` merges them into its SINGLE save_config() call —
        the restore path stays one call per window.
        """
        ratio = self._current_split_ratio()
        if ratio is not None:
            self._split_ratio = max(SPLIT_RATIO_MIN, min(SPLIT_RATIO_MAX, ratio))
        payload = {
            SPLIT_CONFIG_BOOL: bool(getattr(self, "_split_on", False)),
            SPLIT_CONFIG_RATIO: round(float(self._split_ratio), 4),
        }
        if isinstance(extra, dict):
            extra.update(payload)
            return extra
        return payload

    def resizeEvent(self, event):
        """v1.3.3.5 (ROADMAP task 3a): a window resize re-applies the split geometry
        (the proportion is kept, the floors hold). The pane's own canvas resize — and
        therefore the PTY debounce — is handled inside the page (its eventFilter)."""
        super().resizeEvent(event)
        if getattr(self, "_split_on", False):
            self._apply_split_sizes()

    # ── v1.3.3.5: the context menu of the window (the second view of the action) ──

    def _build_context_menu(self):
        """v1.3.3.5 (ROADMAP task 1): the window's context menu — the SAME
        `act_split` QAction as the tab-bar button (one action, two views).

        Test seam (the TerminalWidget pattern): the menu is created by the method, the
        event only shows it, so an offscreen test triggers the QAction directly and
        never runs `menu.exec()`.
        """
        menu = QMenu(self)
        act = getattr(self, "act_split", None)
        if act is not None:
            menu.addAction(act)
        return menu

    def contextMenuEvent(self, event):
        """RMB on a part of the window with no menu of its own (the tab bar, the
        status bar, the split pane's margins) — the split item. The terminal canvas and
        the SFTP tree consume the event for their own menus, so nothing is shadowed."""
        try:
            menu = self._build_context_menu()
            menu.exec(event.globalPos())   # QContextMenuEvent.globalPos() is a QPoint (Qt 6)
        except Exception:  # noqa: BLE001 — a menu failure must not break the window
            pass

    # ── v1.2.1: the "status bar" bridge — the active tab only ────────────────

    def _on_current_tab_changed(self, index: int):
        try:
            page = (self.session_tabs.widget(index)
                    if 0 <= index < self.session_tabs.count() else None)
        except RuntimeError:
            page = None  # the C++ object was already destroyed (a close race)
        # v1.3.3.5: the ACTIVE TAB is the fallback — while the keyboard focus sits in
        # the split pane, switching tabs does not steal the bridge from it.
        if self.focused_split_pane() is not None:
            self._refresh_bridge()
            return
        self._set_bridged_page(page)

    def _set_bridged_page(self, page):
        """Bridge of the ACTIVE tab's signals into the window's status bar
        (the v1.2 look); on tab switch — a reconnect: the status bar shows the
        active session, and inactive tabs' messages do not touch it. The SFTP
        progress bar syncs with the active tab's state (inactive transfers do
        not update the bar)."""
        old = self._bridged_page
        if old is not None and old is not page:
            try:
                old.status_message.disconnect(self._on_page_status_message)
                old.progress_busy.disconnect(self._on_page_progress_busy)
                old.progress_update.disconnect(self._on_page_progress_update)
                old.progress_hidden.disconnect(self._sftp_progress.hide)
            except (TypeError, RuntimeError):
                pass  # the slot was not connected / the C++ object was destroyed — nothing to do
        self._bridged_page = page
        if page is None:
            return
        try:
            page.status_message.connect(self._on_page_status_message)
            page.progress_busy.connect(self._on_page_progress_busy)
            page.progress_update.connect(self._on_page_progress_update)
            page.progress_hidden.connect(self._sftp_progress.hide)
        except RuntimeError:
            return  # the C++ object was already destroyed (a close race) — nothing to bridge
        try:
            if getattr(page, "_sftp_busy", 0) > 0:
                self._sftp_progress.setRange(0, 0)   # until total arrives — busy
                self._sftp_progress.setValue(0)
                self._sftp_progress.show()
            else:
                self._sftp_progress.hide()
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)

    # ── v1.2: bridge "page status bar → window status bar" (look = v1.1.x) ───

    def _on_page_status_message(self, text: str, timeout_ms: int):
        try:
            if timeout_ms > 0:
                self.statusBar().showMessage(text, timeout_ms)
            else:
                self.statusBar().showMessage(text)
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)

    def _on_page_progress_busy(self):
        try:
            self._sftp_progress.setRange(0, 0)   # until total arrives — busy
            self._sftp_progress.setValue(0)
            self._sftp_progress.show()
        except RuntimeError:
            pass

    def _on_page_progress_update(self, done: int, total: int):
        try:
            if total > 0:
                self._sftp_progress.setRange(0, total)
                self._sftp_progress.setValue(done)
            else:
                self._sftp_progress.setRange(0, 0)   # total unknown — busy
        except RuntimeError:
            pass

    # ── v1.2: compat attributes — the session lives on the page (live links) ─

    @property
    def page(self):
        """v1.2.1: the active (current) tab = the "window session"; for a
        single-tab window — the only session (v1.2 compatibility). All the compat
        properties below read it, so existing code/tests work unchanged.

        v1.3.3.5 (ROADMAP task 6): the FOCUSED split pane WINS over the active tab —
        the v1.2.1 "active session" rule extended to the second pane instead of a
        second concept. With the focus elsewhere (the map, another window) the pane is
        not "active" and the property behaves exactly as before.
        """
        pane = self.focused_split_pane()
        if pane is not None:
            return pane
        try:
            cur = self.session_tabs.currentWidget()
            if cur is not None:
                return cur
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)
        return None

    @property
    def terminal_thread(self):
        return self.page.terminal_thread

    @property
    def tscreen(self):
        return self.page.tscreen

    @property
    def widget(self):
        return self.page.widget

    @property
    def tabs(self):
        return self.page.tabs

    @property
    def sftp_tab(self):
        return self.page.sftp_tab

    @property
    def status_label(self):
        return self.page.status_label

    @property
    def _close_behavior(self):
        return self.page._close_behavior

    @property
    def _pty_timer(self):
        return self.page._pty_timer

    @property
    def _last_cols(self):
        return self.page._last_cols

    @_last_cols.setter
    def _last_cols(self, value):
        self.page._last_cols = value

    @property
    def _last_rows(self):
        return self.page._last_rows

    @_last_rows.setter
    def _last_rows(self, value):
        self.page._last_rows = value

    @property
    def _pending_pty(self):
        return self.page._pending_pty

    @_pending_pty.setter
    def _pending_pty(self, value):
        self.page._pending_pty = value

    @property
    def _sftp_worker(self):
        """v1.1.3: the lazy SFTP worker — since v1.2 it lives on the page (a live link)."""
        return self.page._sftp_worker

    # ── v1.2: teardown — the page (a single method) ─────────────────────────

    def close_terminal(self):
        """v1.0RC3 kept for the MainWindow cleanup path: since v1.2 it delegates
        to the page; since v1.2.1 it closes the ACTIVE tab (page.close_terminal →
        host.close_page), not the whole window."""
        p = self.page
        if p is not None:
            p.close_terminal()

    def closeEvent(self, event):
        # v1.1.2RC3 (AUDIT U2): save the window's size/state BEFORE the "ask"
        # dialog — if the user cancels the close (event.ignore), the written values
        # are equal to the current ones anyway; on a normal close they will be read
        # by the next window.
        # v1.3.3.5 (ROADMAP task 5): the split state/ratio ride along in the SAME
        # save_config() call (merged into the geometry write — one write per window).
        try:
            from .window_geometry import save_window_geometry as _save_geo
        except ImportError:
            from modules.window_geometry import save_window_geometry as _save_geo
        try:
            _save_geo("ui_window_geometry_terminal", self, extra=self._save_split_state())
        except Exception:  # noqa: BLE001 — geometry must not block the close
            pass

        # v1.2.1 (task 2): closing the window = closing ALL sessions: the "ask" gate
        # for each active one (Cancel on any of them keeps the window), then the single
        # teardown — page.shutdown() (idempotent) on every page. v1.3.3.5: the SPLIT
        # PANE is a session too (_all_pages) — it is torn down with its window.
        pages = self._all_pages()
        for page in pages:
            try:
                if not page.confirm_close():
                    event.ignore()
                    return
            except RuntimeError:
                pass  # the C++ object was already destroyed — close without asking (as before)
        for page in pages:
            try:
                page.shutdown()
            except Exception:  # noqa: BLE001 — teardown robustness
                pass
        if getattr(self, "_split_pane", None) is not None:
            self._split_pane = None   # the pane is gone with the window (no dangling ref)
        # v1.3.3.5: the application-level focus listener is not needed any more
        try:
            _app = QApplication.instance()
            if _app is not None:
                _app.focusChanged.disconnect(self._on_app_focus_changed)
        except (TypeError, RuntimeError):
            pass  # it was never connected / the C++ object is already gone
        super().closeEvent(event)


