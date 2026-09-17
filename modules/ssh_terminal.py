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

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QMainWindow, QMessageBox, QTabWidget, QProgressBar, QSplitter


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

        # v1.2.1 (task 1): the central widget — a QTabWidget of session pages
        # (each tab = one SSH session). The tabs are closable: closing a tab =
        # the page's existing cleanup logic; the last tab → the window's close().
        self.session_tabs = QTabWidget()
        self.session_tabs.setTabsClosable(True)
        self.session_tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        self.session_tabs.currentChanged.connect(self._on_current_tab_changed)

        # v1.3 (ROADMAP v1.3): the "Terminal Macros" panel to the left of the
        # session tabs — QSplitter [cmdlib_panel | session_tabs]. A double-click/Enter
        # on a command — sends the macro to the ACTIVE session (not the multi-input
        # broadcast). Collapsing into a thin strip (the v1.2.4.1 technique) — the
        # state lives in the single config key ui_cmdlib_collapsed for both
        # containers (window + dock). setCollapsible(False) on both sides: the panel
        # cannot be "lost" by dragging the splitter. The panel's status messages go
        # to the existing _on_page_status_message → statusBar() bridge (the same
        # (str, int) signature, no new bridge code).
        self.cmdlib_panel = CommandLibraryPanel(self.session_tabs, parent=self)
        self.cmdlib_panel.status_message.connect(self._on_page_status_message)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.cmdlib_panel)
        splitter.addWidget(self.session_tabs)
        # setCollapsible AFTER addWidget (Qt: an out-of-range index otherwise):
        # the panel cannot be "lost" by dragging the splitter to zero.
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        self.setCentralWidget(splitter)

        # v1.2 (`windows` mode): the "status bar" is bridged into the window's status
        # bar — sticky text + SFTP progress (a permanent widget on the right, hidden
        # when there are no transfers) exactly as in v1.1.x; since v1.2.1 only the
        # ACTIVE tab is bridged (_set_bridged_page). The page does not know about
        # QMainWindow: in dock mode (v1.2.2) the bridge will attach to the dock.
        self._sftp_progress = QProgressBar()
        self._sftp_progress.setFixedWidth(180)
        self._sftp_progress.setTextVisible(True)
        self._sftp_progress.setVisible(False)
        self.statusBar().addPermanentWidget(self._sftp_progress)
        self._bridged_page = None

        # The first session — via the same path as a new tab (v1.2.1 task 1).
        self.add_session(server_data, password=password, initial_command=initial_command)

    # ── v1.2.1: tabs = sessions ──────────────────────────────────────────────

    def add_session(self, server_data: ServerData, password: str = None,
                    initial_command: str = "") -> "TerminalSessionPage":
        """v1.2.1 (task 1): a new session = a new tab (the existing
        "connect to the node" path). The page is created with parent=session_tabs
        (destroyed together with the window), bound to the host and added as a tab —
        title: the node alias, tooltip: terminal.tab_close_tooltip. The new tab
        becomes active (setCurrentIndex → currentChanged → the signal bridge to the
        status bar)."""
        t = get_translator()
        page = TerminalSessionPage(
            server_data, parent=self.session_tabs,
            password=password, initial_command=initial_command)
        page.set_host_window(self)
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
        (WA_DeleteOnClose — current behaviour)."""
        idx = self.session_tabs.indexOf(page)
        if idx < 0:
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

    # ── v1.2.1: the "status bar" bridge — the active tab only ────────────────

    def _on_current_tab_changed(self, index: int):
        try:
            page = (self.session_tabs.widget(index)
                    if 0 <= index < self.session_tabs.count() else None)
        except RuntimeError:
            page = None  # the C++ object was already destroyed (a close race)
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
        properties below read it, so existing code/tests work unchanged."""
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
        try:
            from .window_geometry import save_window_geometry as _save_geo
        except ImportError:
            from modules.window_geometry import save_window_geometry as _save_geo
        try:
            _save_geo("ui_window_geometry_terminal", self)
        except Exception:  # noqa: BLE001 — geometry must not block the close
            pass

        # v1.2.1 (task 2): closing the window = closing ALL tabs: the "ask" gate
        # for each active session (Cancel on any tab keeps the window), then the
        # single teardown — page.shutdown() (idempotent) on every page.
        try:
            pages = [self.session_tabs.widget(i) for i in range(self.session_tabs.count())]
        except RuntimeError:
            pages = []  # the C++ object was already destroyed — close without asking (as before)
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
        super().closeEvent(event)


