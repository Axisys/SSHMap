import re
import threading
from typing import List

try:
    from ..models.server import ServerData
except ImportError:
    from models.server import ServerData

# ── THE LIVE NAMESPACE OF THE TERMINAL FAMILY (a test seam — do not "clean" it) ──
# terminal_page.py and terminal_dock.py resolve the names IMPORTED BELOW on THIS module
# at call time (`_st_module()`, the `host_attr` pattern) and the tests substitute them
# the same way, so a static "unused import" report on them is the EXPECTED state
# (`AGENTS.md` §4.1); QMessageBox and `TerminalScreen` are the same seam.
try:
    from .terminal_screen import TerminalScreen
except ImportError:
    from modules.terminal_screen import TerminalScreen

# `TerminalWidget` is the live-namespace seam (the `CURSOR_*` / `FONT_SIZE_*` declarations moved
# to `modules/terminal_config.py` with the readers that validate against them).
try:
    from .terminal_widget import TerminalWidget
except ImportError:
    from modules.terminal_widget import TerminalWidget


# v1.1.3 (ROADMAP tasks 1-2): the SFTP tab — a worker thread with a task queue and a UI.
try:
    from .sftp_worker import SftpWorker, register_orphan_sftp_worker
except ImportError:
    from modules.sftp_worker import SftpWorker, register_orphan_sftp_worker

try:
    from .sftp_tab import COMMANDER_CONFIG_BOOL, CommanderCorner, SftpTab, format_size
except ImportError:
    from modules.sftp_tab import COMMANDER_CONFIG_BOOL, CommanderCorner, SftpTab, format_size

# The window is a thin wrapper over a reusable session page (`terminal_page` does NOT
# import this module at module level — it fetches it lazily via `_st_module()`).
# The session area is a vertical QSplitter [session_tabs | split_host] and the host may
# hold a SECOND full session of the SAME node (`add_session(split=True)`, an ordinary
# TerminalSessionPage) — one owner per concern (`DOCUMENTATION.md` §14g).
try:
    from .terminal_page import TerminalSessionPage
except ImportError:
    from modules.terminal_page import TerminalSessionPage

# v1.7.2 (ROADMAP v1.7.2, task 1): the SPLIT is ONE controller shared by both containers — the
# window and the dock. The window keeps the shipped surface as DELEGATES (`split_host`,
# `_v_splitter`, `_split_on`, `split_pane`, `act_split`, `btn_split`, `set_split_enabled()`) and the
# SPLIT_* constants + `load_split_settings` are re-exported HERE, because this module is the live
# namespace the shipped tests read them from (the seam note at the top of the file).
try:
    from .terminal_split import (TerminalSplit, SPLIT_CONFIG_BOOL, SPLIT_CONFIG_RATIO,
                                 SPLIT_RATIO_DEFAULT, SPLIT_RATIO_MIN, SPLIT_RATIO_MAX,
                                 SPLIT_MIN_ROWS, load_split_settings, find_host_hook,
                                 CONTAINER_WINDOW)
except ImportError:
    from terminal_split import (TerminalSplit, SPLIT_CONFIG_BOOL, SPLIT_CONFIG_RATIO,
                                SPLIT_RATIO_DEFAULT, SPLIT_RATIO_MIN, SPLIT_RATIO_MAX,
                                SPLIT_MIN_ROWS, load_split_settings, find_host_hook,
                                CONTAINER_WINDOW)

# v1.6.4 (ROADMAP task 4): the ACTIVITY mark of an inactive session — the rendering is shared
# by BOTH containers (the window and the dock), which is why it lives in the page's module.
try:
    from .terminal_page import refresh_session_activity, render_session_activity
except ImportError:
    from modules.terminal_page import refresh_session_activity, render_session_activity

# Qt imports — only those actually used. `QMessageBox` is NOT a leftover: it is a LIVE
# namespace for the test seams (`_st_module().QMessageBox` is resolved at call time, the
# host_attr pattern), so monkeypatching `ST.QMessageBox.question/critical` works; without it
# `confirm_close("ask")` / `_show_error` would crash. `command_library` does not import us.
try:
    from .command_library import CommandLibraryPanel
except ImportError:
    from command_library import CommandLibraryPanel

from PySide6.QtCore import Qt, QThread, Signal, QEvent, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QMessageBox, QTabWidget, QProgressBar, QSplitter, QMenu, QLabel,
)

try:  # v1.4.3 (ROADMAP task 4): the ONE QSS registry (the status texts below)
    from ..ui import theme_qss
except ImportError:
    try:
        from ui import theme_qss
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        theme_qss = None


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


# ── the session that says it ended ────────────────────────────────────────────
# `TERMINAL_KEEPALIVE_SEC` (30 s) is the interval of the SSH keepalive: one declared constant,
# deliberately NOT a config key — a protocol fact, below every common idle timeout. It is the
# ONLY writer touching an otherwise silent socket, and a socket error makes paramiko unlink
# every channel — which is what makes a peer that vanished without a FIN visible at all.
TERMINAL_KEEPALIVE_SEC = 30

# The SEND path (AGENTS.md §4.3): `Channel.send()` is a PARTIAL write by contract (it answers the
# bytes really put on the wire, clamped to `out_max_packet_size - 64`), so `send_data()` LOOPS on the
# byte count and PARKS the remainder when the window is shut — `error_signal` reaches `_show_error()`,
# which closes the session, so a bare `socket.timeout` must never travel there.
MAX_SEND_QUEUE_BYTES = 8 * 1024 * 1024

# ── the terminal family's CONFIG surface ─────────────────────────────────────
# The keys, the declared values, the panel's floors and the FOUR readers live in
# `modules/terminal_config.py` (ONE home); they are imported HERE because this module is the
# family's live namespace: `_st_module().load_terminal_settings()` and the suite's
# `ST.load_terminal_settings` / `ST.resolve_files_mode` / `ST.FILES_PANEL_*` resolve on it.
try:
    from .terminal_config import (FILES_MODE_CONFIG_KEY, FILES_MODE_DEFAULT, FILES_MODES,
                                 FILES_PANEL_CONFIG_COLLAPSED, FILES_PANEL_MIGRATION_BOOL,
                                 FILES_PANEL_MIN_COLS, FILES_PANEL_MIN_PX,
                                 FILES_PANEL_WIDTH_DEFAULT, TERMINAL_MODES,
                                 load_files_panel_settings, load_terminal_settings,
                                 resolve_files_mode)
except ImportError:  # flat launch from the project root
    from terminal_config import (FILES_MODE_CONFIG_KEY, FILES_MODE_DEFAULT, FILES_MODES,
                                 FILES_PANEL_CONFIG_COLLAPSED, FILES_PANEL_MIGRATION_BOOL,
                                 FILES_PANEL_MIN_COLS, FILES_PANEL_MIN_PX,
                                 FILES_PANEL_WIDTH_DEFAULT, TERMINAL_MODES,
                                 load_files_panel_settings, load_terminal_settings,
                                 resolve_files_mode)


#: The names this module RE-EXPORTS as the terminal family's live namespace (`AGENTS.md` §4.3): the
#: config surface of `modules/terminal_config.py`, read by the suite as `ST.<name>`. The declaration
#: IS the seam — a name read only by a caller is not a dead import.
MODULE_FACADE_SEAMS = (TERMINAL_MODES, FILES_MODE_CONFIG_KEY, FILES_MODE_DEFAULT, FILES_MODES,
                       FILES_PANEL_MIGRATION_BOOL, FILES_PANEL_CONFIG_COLLAPSED,
                       FILES_PANEL_MIN_COLS, FILES_PANEL_MIN_PX, FILES_PANEL_WIDTH_DEFAULT,
                       load_terminal_settings, resolve_files_mode, load_files_panel_settings)


# ── the FILES PANEL widget ───────────────────────────────────────────────────
# The panel and the page's handover live in `modules/terminal_files_panel.py`; it is imported HERE
# because the window builds ONE panel and the shipped tests read the family through this module.
try:
    from .terminal_files_panel import _FilesPanel
except ImportError:  # flat launch from the project root
    from terminal_files_panel import _FilesPanel



# ANSI escape sequences: CSI (ESC [ … final byte), simple escapes (ESC + char) and OSC
# (ESC ] … BEL | ESC \) — the window-title sequences TUI apps (vim/htop) send constantly; without
# stripping them the output keeps garbage like "0;vim". In production pyte parses ANSI, so this helper
# is used only by `tests/test_core.py`: DO NOT REMOVE — see ROADMAP "Do not touch".
ANSI_ESCAPE_RE = re.compile(
    r'\x1B\[[0-?]*[ -/]*[@-~]'   # CSI: ESC [ params final
    r'|\x1B\][^\x07\x1b]*(?:\x07|\x1B\\)'  # OSC: ESC ] ... BEL / ST
    r'|\x1B[@-_]'                # simple two-byte escapes
)


# ── the orphan terminal thread registry (the N4 pattern) ──────────────────────
# The terminal window has WA_DeleteOnClose: closed during a connection, closeEvent waits
# for the thread with `wait(1500)`, while paramiko can block for up to 15 s. The thread is
# created WITHOUT a QObject parent, so a live one must not be left to GC ("QThread:
# Destroyed while running") — the registry keeps it until `finished()` (`AGENTS.md` §4.3).
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
        # v1.6.4 (ROADMAP task 1): the managed session thread names itself — Qt's abort on a
        # thread destroyed while running names an UNNAMED thread as '', and THIS is the class
        # `_orphan_threads` below exists to keep alive until `finished()`. No behaviour.
        self.setObjectName("SSHTerminalThread")
        self.host = host
        self.user = user
        self.port = port
        self.password = password
        self.key_path = key_path
        self.client = None
        self.channel = None
        self.running = True
        # The bytes a send timeout parked (see MAX_SEND_QUEUE_BYTES). Written by the GUI thread
        # (`send_data`) and by the session thread (`_flush_pending`); the lock serialises both the
        # buffer and the channel writes, so two senders can never interleave inside one payload.
        self._send_lock = threading.Lock()
        self._pending = bytearray()
        self._send_overflow_reported = False

    def run(self):
        import paramiko
        t = get_translator()
        # v1.8rc6 (N50): the ONE connect builder (`AGENTS.md` §4.4) — the three branches, the
        # known-hosts policy and the single `connect()` moved to `modules/ssh_connect.py`; this
        # thread keeps the session it opens and the sentences it reports.
        try:
            from .ssh_connect import (CONNECT_TIMEOUT_S, ConnectionCancelled, HostKeyRejected,
                                      connect_client)
        except ImportError:  # flat layout
            from ssh_connect import (CONNECT_TIMEOUT_S, ConnectionCancelled, HostKeyRejected,
                                     connect_client)

        try:
            self.status_signal.emit(t("terminal.connecting", user=self.user, host=self.host, port=self.port))

            # AUDIT v0.7.2 (high #4): known_hosts pinning instead of AutoAddPolicy — the policy is
            # applied by the builder, and the KEY branch passes the password as well: paramiko
            # treats `password` as an AUTH METHOD tried LAST, so it is what makes the main surface
            # (terminal + the Files tab riding the same transport) authenticate on a host where the
            # key alone is refused — the three diagnostic paths already did (v1.7.5.1, N50 minimum).
            client, policy = connect_client(self.host, self.user, self.port,
                                            password=self.password or "",
                                            key_path=self.key_path,
                                            timeout=CONNECT_TIMEOUT_S)

            self.client = client
            self.channel = client.invoke_shell(term='xterm', width=120, height=32)
            self.channel.settimeout(0.2)
            # v1.6.2 (ROADMAP task 1): the SSH-level keepalive — see TERMINAL_KEEPALIVE_SEC.
            # A transport that cannot take it (a fake in a test, a future paramiko) must NOT
            # cost the session: the failure is a log line, never an error signal.
            try:
                client.get_transport().set_keepalive(TERMINAL_KEEPALIVE_SEC)
            except Exception as keepalive_error:  # noqa: BLE001
                try:
                    from modules.logger import get_logger as _gl
                    _gl("modules.ssh_terminal").warning(
                        f"Keepalive could not be enabled for {self.host}: {keepalive_error}")
                except Exception:  # noqa: BLE001 — the logger must never break a session
                    pass
            # v1.0RC4: channel ready — the window may send the first command (Quick Launch)
            self.connected_signal.emit()
            self.status_signal.emit(t("terminal.session_opened"))

            # AUDIT v0.7.2 (high #4): first connection — show the accepted fingerprint
            if policy.accepted_new_key and policy.last_fingerprint:
                note = t("ssh.host_key_new", host=self.host, fp=policy.last_fingerprint)
                self.status_signal.emit(note if not note.startswith("[")
                                        else f"New host key accepted ({policy.last_fingerprint})")
                if not policy.pinned:
                    # v1.7.5.1 (N48): the store was unreadable, so NOTHING was remembered — the
                    # session is running unpinned and the user must be told, not reassured.
                    warn = t("ssh.host_key_unpinned", path=policy.store.path)
                    self.status_signal.emit(warn if not warn.startswith("[")
                                            else "WARNING: host key NOT saved")

            # The loop ends on THREE facts: `channel.closed`, `recv() == b""` (EOF) and
            # `eof_received` / `exit_status_ready()` — each a real end of the session. An EOF must
            # never be discarded: a dropped `b""` made `recv_ready()` True forever, so the loop
            # hot-spun on `recv()` and never signalled. Whatever ends it, `finally` emits
            # `closed_signal` and `_on_closed` writes the ONE status line (§12).
            while self.running and self.channel and not self.channel.closed:
                try:
                    if self.channel.recv_ready():
                        # v0.8: raw bytes with no ANSI stripping — pyte (TerminalScreen) parses them
                        data = self.channel.recv(4096)
                        if not data:
                            break            # EOF — the peer closed the stream
                        self.output_signal.emit(data)
                    elif (getattr(self.channel, "eof_received", False)
                          or self.channel.exit_status_ready()):
                        break                # the peer announced the end of the channel
                    else:
                        # A send window a timeout parked bytes for may have opened: drain it here,
                        # on the session thread, so the GUI-thread `send_data()` never waits.
                        if not self._flush_pending():
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
        except paramiko.AuthenticationException:
            # v1.5rc5 (N4b): the interactive terminal — the PRIMARY "Connect" path — had no
            # localized branch at all, so an auth failure showed paramiko's English sentence
            # in every language and the keys existed but were referenced by the one-shot
            # worker alone. Same class → key mapping as modules/ssh_worker.py.
            if self.running:
                msg = t("ssh.auth_failed")
                self.error_signal.emit(msg if not msg.startswith("[") else "Authentication failed")
        except paramiko.SSHException as e:
            # v1.8.1 (N63): the user's own refusal keeps its FINISHED sentence — a host key that was
            # rejected and a prompt nobody answered are not "SSH error: …".
            if self.running and isinstance(e, (HostKeyRejected, ConnectionCancelled)):
                self.error_signal.emit(str(e))
                return
            if self.running:
                msg = t("ssh.ssh_error", message=str(e))
                self.error_signal.emit(msg if not msg.startswith("[") else f"SSH error: {e}")
        except OSError as e:
            # v1.5rc5 (N4b): socket.gaierror / socket.timeout / NoValidConnectionsError are
            # OSError, not SSHException — see N4. LAST, so the paramiko branches win.
            if self.running:
                msg = t("ssh.connection_failed", host=self.host, port=self.port)
                self.error_signal.emit(msg if not msg.startswith("[")
                                       else f"Connection failed for {self.host}:{self.port}: {e}")
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
        """The ONE input point of the session (AGENTS.md §4.3): ALL the bytes, or none lost.

        Four facts this method owes, each documented in the audit ledger as `N43`:
        the write LOOPS on the byte count (`channel.send()` truncates at ~32 KB by contract), it asks
        the window (`send_ready()`) instead of WAITING for it, so the GUI thread never blocks on the
        peer, a closed or window-less channel PARKS the remainder for the session thread instead of
        emitting an error, and an error message is never EMPTY (`socket.timeout` carries no text,
        and `_show_error()` would show a bare `Error: ` and close the session).
        """
        if not data_bytes:
            return
        if self.channel is None or self.channel.closed:
            return
        with self._send_lock:
            if self._pending:
                # A payload is already parked: keep the FIFO order, the drain owns the channel.
                self._park(data_bytes)
                return
            try:
                sent = self._write_all(data_bytes)
            except Exception as e:  # noqa: BLE001 — the channel died mid-write
                self.error_signal.emit(str(e) or type(e).__name__)
                return
            if sent < len(data_bytes):
                self._park(data_bytes[sent:])

    def _window_open(self) -> bool:
        """Is there room in the channel's send window RIGHT NOW? Never waits (v1.7.5.1).

        `Channel.send()` BLOCKS until the peer opens the window (up to the channel timeout, 0.2 s,
        per call) — and this loop runs on the GUI thread for a keystroke and on the session thread
        for the drain, so waiting here costs a frozen window or a stalled receive loop. `send_ready()`
        is paramiko's own non-blocking answer to exactly this question; a channel without it (a test
        double, an older client) is asked the shipped way, where the send timeout breaks the loop.
        """
        ready = getattr(self.channel, "send_ready", None)
        if not callable(ready):
            return True
        try:
            return bool(ready())
        except Exception:  # noqa: BLE001 — a dead channel is `send()`'s answer, not this one
            return True

    def _write_all(self, data) -> int:
        """Loop `channel.send()` while the window is OPEN and bytes are left; answer the count.

        `TimeoutError` is the SEND timeout of the channel (the receive loop already treats it as a
        normal "nothing yet"), so it BREAKS the loop and lets the caller park the remainder — it is
        never an error. A `0` answer (a closed or `eof_sent` channel) breaks as well: the shipped
        one-shot call dropped those bytes with no error at all.
        """
        channel = self.channel
        sent = 0
        total = len(data)
        while sent < total:
            if not self._window_open():
                break          # the window is shut for now — the caller PARKS the remainder
            try:
                written = channel.send(data[sent:])
            except TimeoutError:
                break
            if not written:
                break
            sent += written
        return sent

    def _park(self, data):
        """Keep the unsent tail for the session thread's next drain. Caller holds `_send_lock`.

        Bounded by MAX_SEND_QUEUE_BYTES: a queue that would overflow drops the OLDEST parked bytes
        and says so ONCE on the status line — a silent drop and an `error_signal` are both wrong
        (the second one closes the session).
        """
        self._pending.extend(data)
        if len(self._pending) > MAX_SEND_QUEUE_BYTES:
            del self._pending[:len(self._pending) - MAX_SEND_QUEUE_BYTES]
            if not self._send_overflow_reported:
                self._send_overflow_reported = True
                try:
                    self.status_signal.emit(get_translator()("terminal.send_queue_full"))
                except Exception:  # noqa: BLE001 — a status line must never break a keystroke
                    pass

    def _flush_pending(self) -> bool:
        """Write what the window refused. True when the window MOVED — the loop retries at once.

        The drain is as non-blocking as the write that parked the bytes (`_window_open()`), so the
        session thread's receive loop is never held behind a send window; a `False` answer is what
        the loop's `msleep(30)` is for.
        """
        with self._send_lock:
            if not self._pending:
                return False
            try:
                sent = self._write_all(bytes(self._pending))
            except Exception as e:  # noqa: BLE001 — an error here must not kill the loop
                self.error_signal.emit(str(e) or type(e).__name__)
                self._pending.clear()
                return False
            if sent:
                del self._pending[:sent]
                self._send_overflow_reported = False
            return sent > 0

    def stop(self):
        self.running = False


# v1.2.9: the SSHTerminalTextEdit HTML path is gone — the keyboard lives in
# TerminalWidget.keyPressEvent.


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

    #: The container KIND a session registry can filter on (`terminal_split.container_windows`):
    #: the merge and the `"single"` mode collect terminal WINDOWS and never the dock.
    CONTAINER_KIND = CONTAINER_WINDOW

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
        self._split_config = load_split_settings()

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

        # The SPLIT — v1.7.2 moves the furniture into `modules/terminal_split.py`, instantiated
        # here: `_v_splitter` is [session_tabs | split_host] and the shipped names below are
        # DELEGATES of the controller (the "a shipped name resolves on the owner" rule).
        self.split = TerminalSplit(self)
        self.split_host = self.split.host
        self._v_splitter = self.split.splitter

        # The "Terminal Macros" panel to the left of the session tabs —
        # QSplitter [cmdlib_panel | QSplitter(session_tabs | split_host)]. A double-click /
        # Enter sends the macro to the ACTIVE session (never the multi-input broadcast: the
        # panel asks the container for the FOCUSED session); the collapse state is the ONE
        # config key `ui_cmdlib_collapsed` for both containers (`DOCUMENTATION.md` §14).
        self.cmdlib_panel = CommandLibraryPanel(self.session_tabs, parent=self)
        self.cmdlib_panel.status_message.connect(self._on_page_status_message)
        self.cmdlib_panel.set_active_session_provider(self.active_session)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.cmdlib_panel)
        splitter.addWidget(self._v_splitter)
        # v1.7.1 (ROADMAP v1.7.1): the FILES PANEL — the third column of the same splitter,
        # the mirrored RIGHT half of the command panel. It carries the ACTIVE session's Files
        # tree (`_FilesPanel.stack`, one page per session) instead of a Files TAB, and it is
        # hidden while the mode is off (a hidden splitter member costs no geometry, exactly
        # like `split_host`). The state/keys are read BEFORE the first session is added.
        self._files_config = load_files_panel_settings()
        self._files_panel_on = False
        #: tab (SftpTab) → the two-pane view it had when the panel forced the mode OFF
        #: (the MUTUAL EXCLUSION: the panel is single-pane, the state is KEPT and restored).
        self._commander_kept = {}
        self.files_panel = _FilesPanel(self)
        splitter.addWidget(self.files_panel)
        # setCollapsible AFTER addWidget (Qt: an out-of-range index otherwise):
        # the panel cannot be "lost" by dragging the splitter to zero.
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setCollapsible(2, False)
        self.files_panel.hide()
        self.setCentralWidget(splitter)

        # ONE checkable action (`terminal.split`) drives BOTH surfaces — the BUTTON in the
        # right corner of the tab bar and the window's context-menu item — and carries NO
        # keyboard shortcut. The action, the button and their wiring belong to the controller
        # (`modules/terminal_split.py`), so a second container builds the same construct
        # (`DOCUMENTATION.md` §14g).
        self.act_split, self.btn_split = self.split.build_action()
        # The right corner of the session tab bar — the natural place of a per-session
        # action (the left side belongs to the command panel). A tab bar has ONE corner
        # widget, so the corner is a container holding the shipped PAIR: the split button
        # and the Files Commander action of the ACTIVE session. The control is a VIEW of the
        # session's state (`_sync_commander()` re-reads it on a tab switch), `SFTP_PANES.md`.
        self.act_files_panel = QAction(t("terminal.files_panel"), self)
        self.act_files_panel.setCheckable(True)
        self.act_files_panel.setToolTip(t("terminal.files_panel_tooltip"))
        self.act_files_panel.toggled.connect(self.set_files_panel_enabled)
        # v1.7.2 (task 5): the MERGE — every OTHER live terminal window's sessions move into
        # THIS one (context-menu item only; no registry sequence, no fourth corner button).
        self.act_merge = QAction(t("terminal.merge_windows"), self)
        self.act_merge.triggered.connect(self._on_merge_windows)
        self.commander = CommanderCorner(self, split_button=self.btn_split)
        self.commander.act.toggled.connect(self._on_commander_toggled)
        self.session_tabs.setCornerWidget(self.commander, Qt.Corner.TopRightCorner)

        # The "status bar" of a session is BRIDGED into the window's status bar — sticky text +
        # the SFTP progress widget (hidden while there are no transfers). Only the ACTIVE tab is
        # bridged, and with a split the FOCUSED pane wins. The bar is the ONE status surface of
        # the window (the page draws none), and the pane's own line (`terminal.split`) is a
        # PERMANENT widget too, so a transient SFTP message cannot wipe it.
        self._split_status_text = ""
        self._split_status_label = QLabel("")
        if theme_qss is not None:
            self._split_status_label.setStyleSheet(
                theme_qss.style("status.terminal_row"))
        self._split_status_label.hide()
        self.statusBar().addPermanentWidget(self._split_status_label)
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

        # The OPENING Files display mode of this window. It is the setting's job to decide how a window
        # opens (the `terminal_mode` convention: "applied to new windows; open ones live on as-is"), so the
        # key is read HERE and the mode is installed through the ONE action (`toggled` →
        # `set_files_panel_enabled`); the fold rides along. A live toggle of the window's own context-menu
        # item is a per-window override and is deliberately NOT written back (`AGENTS.md` §4.3).
        self.files_panel.set_collapsed(self._files_config["collapsed"], persist=False)
        if self._files_config["mode"] == "panel":
            self.act_files_panel.setChecked(True)

    # ── v1.3.3.1 (ROADMAP task 1): live i18n — re-text on a language switch ──

    def retranslate(self):
        """v1.3.3.1: re-text the window and its sessions in the current language.

        The window title (`terminal.window_title`), the close tooltip of every tab
        (`terminal.tab_close_tooltip`) and — through each page — the `Terminal | Files`
        titles, the SFTP buttons/headers and the command-library panel. Every string
        already has an i18n key (ZERO new keys); the module translator is looked up at
        call time, so its cache needs no invalidation.

        v1.7.2 (tasks 3/6): the SPLIT action's label and tooltip are the controller's (one label,
        one tooltip, two views, plus the owner's alias), and the window title names the session ON
        SCREEN — a shared window cannot keep naming the first one. Never raises.
        """
        t = get_translator()
        # v1.2.3: the multi-input prefix lives on the window title (multi_input.py); the base is
        # recomputed from the session ON SCREEN, so the prefix is re-added instead of lost.
        self._refresh_window_title()
        # v1.3.3.5: the split action (the tab-bar BUTTON and the context-menu item).
        self.split.retranslate()
        # v1.7.2 (task 5): the merge item of the context menu.
        act_merge = getattr(self, "act_merge", None)
        if act_merge is not None:
            try:
                act_merge.setText(t("terminal.merge_windows"))
            except RuntimeError:
                pass  # Qt teardown — the action is already destroyed
        # v1.7.1.1: the Files panel switch — ONE label and ONE tooltip, and ONE view left:
        # the window's context-menu item (the corner button is gone; the mode lives in the
        # settings hub). The panel's own chrome re-texts itself below.
        act_panel = getattr(self, "act_files_panel", None)
        if act_panel is not None:
            try:
                act_panel.setText(t("terminal.files_panel"))
                act_panel.setToolTip(t("terminal.files_panel_tooltip"))
            except RuntimeError:
                pass  # Qt teardown — the action is already destroyed
        files_panel = getattr(self, "files_panel", None)
        if files_panel is not None:
            try:
                files_panel.retranslate()
            except RuntimeError:
                pass  # Qt teardown — the panel is already destroyed
        # v1.7rc1: the Files Commander control of the same corner (its label and tooltip).
        commander = getattr(self, "commander", None)
        if commander is not None:
            commander.retranslate()
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
        # v1.6.4 (ROADMAP task 4): the activity mark's TOOLTIP is translated text — an inactive
        # session keeps its dot across a language switch, with the sentence in the new language
        # (the mark itself is a pixmap, re-rendered by refresh_theme()).
        refresh_session_activity(self)
        # v1.3.3.1: the "Terminal macros" panel belongs to the CONTAINER (both the
        # window and the dock own one), so it is re-texted here — not by the page.
        cmdlib = getattr(self, "cmdlib_panel", None)
        if cmdlib is not None:
            try:
                cmdlib.retranslate()
            except RuntimeError:
                pass  # Qt teardown — the panel is already destroyed
        # v1.4.7 follow-up: the split text carries the `terminal.split` PREFIX — the
        # raw pane state is LIVE session data (never re-translated, §4.5), the prefix
        # around it is a string of the ACTIVE language.
        self._render_split_status()

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
        # v1.4.7 follow-up: the split text is a widget-level stylesheet of this window
        # (the page's status labels went away with its status line).
        if theme_qss is not None:
            try:
                theme_qss.refresh(self._split_status_label, "status.terminal_row")
            except RuntimeError:
                pass  # Qt teardown — the label is already destroyed
        # v1.6.4 (ROADMAP task 4): the activity mark is a PIXMAP — a VALUE (§4.6): re-render it
        # in the new theme tone instead of leaving the old colour on the tab.
        refresh_session_activity(self)
        # v1.7.1: the Files panel's hand-painted chrome (its strip and its fold button).
        files_panel = getattr(self, "files_panel", None)
        if files_panel is not None:
            hook = getattr(files_panel, "refresh_theme", None)
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
            # The pane is a COMMAND LINE — no SFTP tab (a second channel, a second worker and a file
            # tree squeezed into ~130 px are pure cost there) and no status line either
            # (`with_status_line=False`): the pane's live state goes onto its inner `Terminal` tab
            # instead of a whole row under the canvas, measured at ~25 px of a ~140 px pane. It also
            # keeps the page's layout minimum small, which is what makes the 25% default honest.
            page = TerminalSessionPage(
                server_data, parent=self.split_host, with_sftp=False,
                with_status_line=False, split=True,
                password=password, initial_command=initial_command)
            page.set_host_window(self)
            # v1.6.1 (task 8): the constructor already marks the pane (it decides the
            # keyboard claim); the assignment stays as the ONE visible statement of the
            # marker this block is built around.
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
        idx = self.session_tabs.addTab(page, self._session_tab_title(page))
        # Qt: addTab makes only the FIRST tab current — activate the new one
        # explicitly (currentChanged → the signal bridge to the status bar).
        self.session_tabs.setCurrentIndex(idx)
        # v1.6.4 (ROADMAP task 4): the FIXED icon slot (a transparent mark) + the ordinary close
        # tooltip of a fresh tab — through the ONE renderer, so a later mark can never change
        # the width of this tab.
        render_session_activity(self.session_tabs, page, t)
        # v1.7.1: a session born while the Files panel is ON joins the stack — its Files tab
        # is taken away here and comes back the moment the mode goes off (ONE attach path).
        if self._files_panel_on:
            self._attach_files_panel_page(page)
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
        # v1.7.1: a session in the Files panel gives its widget BACK before it dies (AFTER the
        # "ask" gate — a cancelled close must leave the panel exactly as the user sees it).
        # The widget's parent is the panel's stack while the mode is on, so without this the
        # Files tree would outlive the session it belongs to (an orphan page in the stack),
        # and the remembered two-pane state of a session nobody can reach any more goes with it.
        self._release_files_panel_page(page)
        self._commander_kept.pop(getattr(page, "sftp_tab", None), None)
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

    # ── the SPLIT — a second pane under the sessions ──
    # ONE owner per concern: `act_split` (`terminal.split`) is the tab-bar button and the
    # context-menu item; the LAYOUT is `[session_tabs | split_host]`, hidden while the split
    # is off; the SESSION is an ordinary `TerminalSessionPage(split=True)` with its own
    # thread, screen and idempotent `shutdown()`; `_is_split_pane` keeps it out of the limit.

    @property
    def split_pane(self):
        """The live split pane (None while the split is off) — a DELEGATE of the controller.

        The container exposes it for the multi-input highlight
        (modules/multi_input.py walks the session tabs and reaches the pane here).
        """
        return self.split.pane

    @property
    def _split_pane(self):
        """The controller's pane under the name every shipped caller and test reads."""
        return self.split.pane

    @_split_pane.setter
    def _split_pane(self, value):
        self.split.pane = value

    @property
    def _split_on(self):
        """Is a pane open at all (the pane survives a tab switch to a foreign session)."""
        return self.split.on

    @_split_on.setter
    def _split_on(self, value):
        self.split.on = bool(value)

    @property
    def _split_ratio(self):
        """The pane's share of the height, remembered across opens."""
        return self.split.ratio

    @_split_ratio.setter
    def _split_ratio(self, value):
        self.split.ratio = float(value)

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
        pane = self.split.pane
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

    def set_split_enabled(self, on: bool) -> bool:
        """v1.3.3.5 (ROADMAP tasks 1/2/3) + v1.7.2 (task 3): the ONE split switch.

        ON — the pane is created for the ACTIVE session (a REAL second session of the same node: a
        fresh SSHTerminalThread with that session's credentials, WITHOUT its Quick Launch command
        and WITHOUT forcing the SFTP worker), the host is shown and the sizes come from the stored
        ratio (default 0.25 of the height). A press while a FOREIGN session owns the pane MOVES it
        (the old pane passes its own gate first). OFF — the "ask" gate of the pane
        (`page.confirm_close()`, the SAME gate every other session close uses) and the single
        teardown `page.shutdown()`; a Cancel leaves the pane open and puts the checkmark back
        without re-entering this slot. Returns True when the requested state was reached.
        """
        return self.split.set_enabled(on)

    def _open_split_pane(self):
        """Create and show the split pane (idempotent — already open ⇒ no-op)."""
        return self.split.open_pane()

    def _close_split_pane(self) -> bool:
        """Tear the pane down; False — the "ask" gate was cancelled (the pane stays)."""
        return self.split.close_pane()

    def _wire_page(self, page):
        """v1.3.3.5 (ROADMAP task 6): let the window follow the FOCUS of a canvas.

        The bridge and `win.page` follow the ACTIVE TAB — and, with a
        split, two sessions on the screen at once — the FOCUS as well; the container follows
        the focus there. The canvas FocusIn filter is the cheap first half — the
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
        guarding for ancestry first. v1.7.2: the split action and the window title are
        re-read here too — the whole "who owns the pane / whose name is on the window"
        answer follows the keyboard, not the tab strip.
        """
        self._refresh_bridge()
        self.split.sync_owner()
        self._refresh_window_title()

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
        pane = self.split.pane
        if pane is not None:
            pages.append(pane)
        return [p for p in pages if p is not None]

    def split_server_data(self, page=None):
        """The node of the pane — the OWNER session's data (fallback: the window's)."""
        if page is None:
            try:
                page = self.session_tabs.currentWidget()
            except RuntimeError:
                page = None
        data = getattr(page, "server_data", None)
        return data if data is not None else self.server_data

    def split_password(self, page=None):
        """The credentials of the pane — the SAME node, the SAME password as its own session
        (the explicit one the session was created with is kept on the thread; the model itself
        never carries it, AUDIT v0.7.2 medium #7)."""
        if page is None:
            try:
                page = self.session_tabs.currentWidget()
            except RuntimeError:
                page = None
        thread = getattr(page, "terminal_thread", None)
        return getattr(thread, "password", "") or ""

    def _split_server_data(self):
        """v1.3.3.5 compat reader: the node of the pane (see `split_server_data`)."""
        return self.split_server_data()

    def _split_password(self):
        """v1.3.3.5 compat reader: the credentials of the pane (see `split_password`)."""
        return self.split_password()

    def _session_sink(self):
        """v1.3.3.5 (ROADMAP task 2): the host's session-registry hook, on the PARENT CHAIN.

        The pane is a real session (green dot, multi-input) that was NOT created by
        `SshMixin._spawn_terminal_window`, so it must reach `MainWindow._terminal_windows`
        through the host — duck-typed, because `modules/*` never imports `ui.main_window`
        (the cycle rule) and a test window may be created with parent=None (the pane then
        simply lives and dies with it). v1.7.2: the walk is what lets the DOCK reach the
        same hook through `TerminalsDock` without a constructor argument.
        """
        return find_host_hook(self, "_adopt_split_session")

    def _register_split_session(self, page):
        """Hand the pane to the host registry (a no-op without a host — see above)."""
        sink = self._session_sink()
        if sink is None:
            return
        try:
            sink(page)
        except Exception:  # noqa: BLE001 — the registry must never break the split
            pass

    def _attach_split_pane(self, pane) -> bool:
        """The container's half of "the pane is open": its status text and the keyboard bridge.

        The pane has NO status line and NO tab strip of its own, so its live state is rendered as
        the SECOND text of this window's status bar — connected here, dropped in
        `_detach_split_pane`. The canvas of a fresh pane takes the focus
        (`TerminalSessionPage.__init__`), so the bridge follows it right away (no FocusIn event is
        guaranteed). Never raises.
        """
        try:
            pane.status_message.connect(self._on_split_status_message)
        except (RuntimeError, AttributeError):
            pass  # a test double / a teardown race — the pane simply has no line
        try:
            self._on_split_status_message(pane.session_status, 0)
        except (RuntimeError, AttributeError):
            pass  # a test double without the property — no line to render
        self._refresh_bridge()
        return True

    def _detach_split_pane(self, pane) -> bool:
        """The pane's line leaves the status bar together with the pane (idempotent)."""
        self._hide_split_status(pane)
        return True

    def _set_split_action_checked(self, checked: bool):
        """Set the action's checkmark (and the BUTTON mirroring it) WITHOUT re-entering
        the slot — the "ask" gate of the pane: a Cancel must leave the pane open and the
        control pressed."""
        self.split.sync_action(checked)

    def _sync_split_button(self, checked=None):
        """Keep the corner BUTTON in step with the ONE action (idempotent, never raises)."""
        self.split.sync_button(checked)

    def _on_split_button_clicked(self, _checked=False):
        """The BUTTON asks the ACTION (one source of truth): the click does not change
        the state itself — `set_split_enabled()` does, through the action's `toggled`."""
        self.split.on_button_clicked(_checked)

    # ── the Files Commander of the ACTIVE session ──
    # The two-pane view lives on the PAGE (`page.sftp_tab`, the `SftpTab` container), while the control
    # that drives it is the tab bar's — one corner widget for the whole window. The window keeps them in
    # step in ONE place (`_sync_commander`, called from the bridge that already knows which session is on
    # screen) and routes the control's click into the active session's own `set_commander()`.

    def _commander_tab(self):
        """The Files tab of the ACTIVE session (None — no session / no SFTP channel).

        The BRIDGED page is the session on screen (it already follows the FOCUSED split pane,
        §4.3), so the corner control and the mode it drives always speak about the same
        session — the `self.page` fallback covers the moment before the first bridge.

        A SPLIT PANE is built `with_sftp=False`, so its `sftp_tab` is None and the action
        is DISABLED there: a second Files tab inside a command line makes no sense.
        """
        page = self._bridged_page or self.page
        return getattr(page, "sftp_tab", None)

    def _on_commander_toggled(self, on: bool):
        """The corner control asked for the two-pane view of the ACTIVE session."""
        if self.files_panel_on:
            # v1.7.1: the Files panel is single-pane, so the control is DISABLED while it is
            # on — this is a stale signal; the session's state is never touched (the kept
            # state is the window's and comes back when the panel goes off).
            self._sync_commander()
            return
        tab = self._commander_tab()
        ok = False
        if tab is not None:
            try:
                ok = bool(tab.set_commander(bool(on)))
            except (RuntimeError, AttributeError):
                ok = False
        if ok and on:
            # v1.7rc1: the panes are built inside the Files tab — the door brings them on
            # screen (and opens the SFTP channel lazily on the way).
            self._show_files_tab()
        if not ok:
            # no session to serve / the second pane could not be created — the checkmark
            # goes back (the `set_split_enabled()` discipline: never a pressed button over
            # a state that is not there).
            self._sync_commander(force_off=True)

    def _show_files_tab(self):
        """Ask the ACTIVE session to show its Files tab (a page without one answers False)."""
        page = self.page
        hook = getattr(page, "show_files_tab", None)
        if callable(hook):
            try:
                hook()
            except RuntimeError:
                pass  # Qt teardown — the page is already destroyed

    def _sync_commander(self, force_off: bool = False):
        """Show the ACTIVE session's mode in the corner control (the ONE place).

        The action's signals stay BLOCKED while the state is written, so a tab switch
        re-shows the mode without re-entering the slot that owns it (the
        `_set_split_action_checked` discipline) — and a mode belongs to its own session,
        never to the window.
        """
        corner = getattr(self, "commander", None)
        if corner is None:
            return
        tab = None if force_off else self._commander_tab()
        try:
            # v1.7.1: the Files panel is SINGLE-PANE, so the two-pane view of the ACTIVE
            # session is DISABLED while the panel is on (its state is KEPT — see
            # `_keep_commander_state()` — and comes back the moment the mode goes off).
            corner.set_enabled(tab is not None and not self._files_panel_on)
            corner.set_state(bool(tab is not None and tab.commander))
        except RuntimeError:
            pass  # teardown — the corner is gone

    # `[commands | terminal | files]` at once: the ACTIVE session's Files widget is RE-PARENTED
    # from its tab strip into `_FilesPanel.stack` (ONE page per session, so the strip reads
    # `Terminal | History`) while the page KEEPS `page.sftp_tab` as the OWNER — the browsed
    # directory, the viewer and every page-level read survive. The mode is `terminal_files_mode`
    # (`resolve_files_mode()`); the layout, the fold, the channel and the persistence — §63.

    def _tab_pages(self) -> list:
        """Every live session that CARRIES A TAB (the split pane is deliberately not one)."""
        try:
            pages = [self.session_tabs.widget(i) for i in range(self.session_tabs.count())]
        except RuntimeError:
            pages = []   # the C++ object was already destroyed (a close race)
        return [p for p in pages if p is not None]

    @property
    def files_panel_on(self) -> bool:
        """Is the Files tree shown in the right-hand panel (and therefore out of the tabs)?"""
        return bool(getattr(self, "_files_panel_on", False))

    def set_files_panel_enabled(self, on: bool):
        """v1.7.1: the ONE switch of the Files panel — called from `act_files_panel.toggled`.

        ON — the panel is shown, every session's Files widget moves into its stack, the
        two-pane view of each session is forced OFF and REMEMBERED, the canvas gets its
        column floor and the panel its opening width.
        OFF — every widget goes back to the tab it came from, the remembered two-pane states
        are restored and both floors are dropped (the shipped look, exactly).
        Idempotent and teardown-safe.
        """
        on = bool(on)
        if on == self._files_panel_on:
            self._set_files_panel_action_checked(on)
            return
        if on:
            self._open_files_panel()
        else:
            self._close_files_panel()
        self._set_files_panel_action_checked(self._files_panel_on)

    def _open_files_panel(self):
        """Show the panel and move every session's Files widget into it. Never raises."""
        pages = [p for p in self._tab_pages() if getattr(p, "sftp_tab", None) is not None]
        if not pages:
            self._files_panel_on = False   # nothing to serve — the checkmark goes back
            return
        self._files_panel_on = True
        self._keep_commander_state()
        for page in pages:
            self._attach_files_panel_page(page)
        try:
            self.files_panel.set_collapsed(self.files_panel.is_collapsed(), persist=False)
            self.files_panel.show()
        except RuntimeError:
            # Qt teardown — the panel died inside its own open: the ONE teardown path puts the
            # flag, the attached widgets and the kept two-pane state back where reality is,
            # because the caller renders `_files_panel_on` as the action's checkmark.
            self._close_files_panel()
            return
        self._refresh_files_panel_current()
        self._apply_files_panel_sizes()
        # the layout of a just-shown member settles after the event cycle (the page's own
        # singleShot(0) grid sync is the same pattern) — a second pass on the real sizes.
        try:
            QTimer.singleShot(0, self._apply_files_panel_sizes)
        except RuntimeError:
            pass
        self._sync_commander()

    def _close_files_panel(self):
        """Hide the panel and hand every Files widget back to its own session. Never raises."""
        # the width the user is looking at becomes the one the next open comes back to.
        try:
            self.files_panel.remember_width()
        except RuntimeError:
            pass
        self._files_panel_on = False
        for page in self._tab_pages():
            self._release_files_panel_page(page)
        try:
            self.files_panel.release_floors()
        except RuntimeError:
            pass   # the panel's own floor is gone with it; the window's is reset below
        try:
            self.files_panel.hide()
        except RuntimeError:
            pass
        self._reset_files_panel_floors()
        self._restore_commander_state()
        self._sync_commander()

    def _attach_files_panel_page(self, page) -> bool:
        """Move ONE session's Files widget into the panel (the tab goes away with it)."""
        hook = getattr(page, "detach_files_tab", None)
        widget = None
        if callable(hook):
            try:
                widget = hook()
            except (RuntimeError, AttributeError):
                widget = None   # Qt teardown / a page without the hook — nothing moved
        if widget is None:
            return False
        try:
            self.files_panel.attach_page(page, widget)
        except RuntimeError:
            return False
        # the PAGE's own half: the flag decides the lazy channel open (there is no Files tab
        # left to switch to), so it is set for a page whose widget really moved.
        setter = getattr(page, "set_files_panel", None)
        if callable(setter):
            try:
                setter(True)
            except (RuntimeError, AttributeError):
                pass
        return True

    def _release_files_panel_page(self, page) -> bool:
        """Hand ONE session's Files widget back to its own tab strip (idempotent).

        Safe to call with the mode already OFF (the `close_page` path does): a widget the
        stack does not carry is not touched at all, so the tab is never inserted twice. The
        KEPT two-pane state is deliberately NOT dropped here — a mode that goes off RESTORES
        it (`_restore_commander_state()`), and only a session that really dies forgets it
        (`close_page` pops its entry).
        """
        try:
            moved = self.files_panel.detach_page(page)
        except RuntimeError:
            moved = False
        if not moved:
            return False
        setter = getattr(page, "set_files_panel", None)
        if callable(setter):
            try:
                setter(False)
            except RuntimeError:
                pass
        hook = getattr(page, "attach_files_tab", None)
        if callable(hook):
            try:
                hook()
            except RuntimeError:
                pass   # Qt teardown — the widget dies with the page either way
        return True

    def _refresh_files_panel_current(self) -> bool:
        """Show the ACTIVE tab's own tree — the stack follows `session_tabs.currentChanged`."""
        if not self._files_panel_on:
            return False
        try:
            page = self.session_tabs.currentWidget()
        except RuntimeError:
            return False
        try:
            return bool(self.files_panel.set_current(page))
        except RuntimeError:
            return False

    # ── v1.7.1: the mutual exclusion with the Files Commander ────────────

    def _keep_commander_state(self):
        """Force the two-pane view OFF and REMEMBER it — the panel mode is single-pane.

        The state is kept (NOT discarded), so switching the panel off restores exactly the
        two-pane view the session had; `_save_split_state()` writes the KEPT state, so closing
        the window with the panel on does not cost the user the mode either.
        """
        for page in self._tab_pages():
            tab = getattr(page, "sftp_tab", None)
            if tab is None:
                continue
            try:
                if tab.commander:
                    self._commander_kept[tab] = True
                    tab.set_commander(False)
            except (RuntimeError, AttributeError):
                continue   # Qt teardown — that session is already gone

    def _restore_commander_state(self):
        """Give every session back the two-pane view the panel took away. Never raises."""
        kept = dict(self._commander_kept)
        self._commander_kept = {}
        for tab, want in kept.items():
            if not want:
                continue
            try:
                tab.set_commander(True)
            except (RuntimeError, AttributeError):
                continue   # Qt teardown — that session is already gone

    # ── v1.7.1: the geometry of the mode (the mirror of the split's floors) ──

    def _files_panel_min_width(self) -> int:
        """The CANVAS floor of the mode, in PIXELS — `FILES_PANEL_MIN_COLS` live cells.

        Built, not guessed (the `_split_min_height()` rule): the cell width comes from the
        session's own metrics, so a narrow window keeps the columns it really needs instead
        of squeezing the terminal into an unreadable strip.
        """
        col_w = 8
        try:
            col_w = max(1, int(self.page.widget.cell_size[0]))
        except (RuntimeError, AttributeError, TypeError, IndexError):
            col_w = 8   # a dying C++ object / a page without a canvas — a sane default
        return int(col_w * FILES_PANEL_MIN_COLS)

    def _apply_files_panel_floors(self):
        """Install the column floor of the canvas and the width floor of the panel.

        A FOLDED panel keeps the strip's own 24 px (its cap must win): the floor of an open
        panel is applied by `_FilesPanel._apply_panel_width(False)`, so raising it here would
        make the minimum beat the collapsed maximum (Qt: `minimumWidth` wins) and leave a
        200 px "strip" behind.
        """
        floor = self._files_panel_min_width()
        try:
            self._v_splitter.setMinimumWidth(floor)
        except RuntimeError:
            return   # C++ teardown — nothing to floor
        for page in self._all_pages():
            try:
                page.widget.setMinimumWidth(floor)
            except (RuntimeError, AttributeError):
                continue   # Qt teardown / a page without a canvas
        try:
            collapsed = bool(self.files_panel.is_collapsed())
            self.files_panel.setMinimumWidth(0 if collapsed else FILES_PANEL_MIN_PX)
        except RuntimeError:
            pass

    def _reset_files_panel_floors(self):
        """Drop both floors (the mode is off — the shipped window minimum comes back)."""
        try:
            self._v_splitter.setMinimumWidth(0)
        except RuntimeError:
            pass
        for page in self._all_pages():
            try:
                page.widget.setMinimumWidth(0)
            except (RuntimeError, AttributeError):
                continue   # Qt teardown / a page without a canvas

    def _apply_files_panel_sizes(self):
        """Give the panel its width (the fold's cap, or the width it remembers)."""
        if not self._files_panel_on:
            return
        try:
            self.files_panel.apply_width()
        except RuntimeError:
            return   # C++ teardown — nothing to size
        self._apply_files_panel_floors()

    # ── v1.7.1: the action and its checkmark (the compat mirroring) ──────

    def _set_files_panel_action_checked(self, checked: bool):
        """Set the checkmark WITHOUT re-entering the slot (the `btn_split` discipline).

        v1.7.1.1: the checkmark is the ONLY view of the state left — the corner button is
        gone, so there is nothing to mirror. Kept as the ONE write path, because the switch
        itself (`set_files_panel_enabled`) corrects the action when it could not do what it
        was asked (no session to serve, a teardown race).
        """
        checked = bool(checked)
        act = getattr(self, "act_files_panel", None)
        if act is not None:
            try:
                act.blockSignals(True)
                act.setChecked(checked)
                act.blockSignals(False)
            except RuntimeError:
                pass   # teardown — the action is gone

    def _split_min_height(self) -> int:
        """v1.3.3.5 (ROADMAP task 3a): the size floor of the bottom pane, in PIXELS.

        The floor is BUILT, not guessed (`SPLIT_MIN_ROWS` rows measured from the live cell
        metrics + the pane's own CHROME measured from the live geometry) and installed as an
        explicit `minimumHeight` (an explicit minimum overrides `minimumSizeHint` — that is
        what turns the floor into the splitter's own limit). The arithmetic is the
        controller's (`TerminalSplit.min_height`, `DOCUMENTATION.md` §14g). Never raises.
        """
        return self.split.min_height()

    def _current_split_ratio(self):
        """The pane's CURRENT share of the splitter height (None — nothing to measure).

        None while the split is OFF or while the host is hidden (its size is 0): a ratio
        measured on a hidden member would be 0 and would OVERWRITE the proportion the user
        left behind — the last real proportion is kept instead.
        """
        return self.split.current_ratio()

    def _on_split_moved(self, _pos=None, _index=None):
        """v1.3.3.5 (ROADMAP task 3a): the user dragged the divider — the new
        proportion becomes THE ratio, so the next window resize keeps it (the explicit
        drag is respected; the clamp only guards the unusable extremes)."""
        return self.split.on_moved(_pos, _index)

    def _apply_split_sizes(self):
        """v1.3.3.5 (ROADMAP task 3a): the two geometry answers of the split.

        (1) The pane is a FRACTION of the height, so a window resize keeps the proportion —
            applied on open, on every resize and after the user drags the divider;
        (2) both panes get a FLOOR of a few rows, so the divider can never collapse one of
            them into unusability — the floor is expressed as `setMinimumHeight` + `setSizes`
            (Qt gotcha #13 forbids `setMaximum*` on a splitter member). The arithmetic is the
            controller's (`TerminalSplit.apply_sizes`, `DOCUMENTATION.md` §14g).
        """
        return self.split.apply_sizes()

    def _reset_split_floors(self, pane=None):
        """Drop the floors of `_apply_split_sizes` with the pane (the single-pane window
        minimum returns exactly). `pane` is passed explicitly by the close path, where the
        pane is already detached from the controller's state."""
        return self.split.reset_floors(pane)

    def _save_split_state(self, extra: dict = None) -> dict:
        """v1.3.3.5 (ROADMAP task 5): the window's persistence payload for ONE `save_config()`.

        Returns the extra top-level keys of the geometry write — the split's two
        (`ui_terminal_split` + `ui_terminal_split_ratio`, from the controller), the Files
        panel's FOLD (UI state, the `ui_cmdlib_collapsed` rule; the MODE is the settings hub's
        `terminal_files_mode` and is deliberately NOT written back) and the Files Commander
        state/ratio of the ACTIVE session — so `closeEvent` merges them into its SINGLE write.
        """
        payload = dict(self.split.state_payload())
        payload[FILES_PANEL_CONFIG_COLLAPSED] = bool(self.files_panel.is_collapsed())
        # v1.7rc1 (ROADMAP v1.7rc1, task 5): the Files Commander state/ratio of the ACTIVE
        # session ride along in the very same write — ONE save_config() per window. While
        # the keyboard sits in the SPLIT PANE the bridged page has no Files tab, so the mode
        # of the ACTIVE TAB is written instead: the window remembers a session's state.
        tab = self._commander_tab()
        if tab is None:
            try:
                tab = getattr(self.session_tabs.currentWidget(), "sftp_tab", None)
            except RuntimeError:
                tab = None
        if tab is not None:
            try:
                tab.commander_extra_config(payload)
            except (RuntimeError, AttributeError):
                pass  # a page without the container / a teardown race — the split keys stay
            # v1.7.1: with the Files panel ON the live mode is forced OFF, so the KEPT state
            # is what the user really had — a close must not cost them the two-pane view.
            if self._commander_kept.get(tab):
                payload[COMMANDER_CONFIG_BOOL] = True
        # v1.7.3 (ROADMAP v1.7.3, task 2): the per-server directory memory of EVERY session of this
        # container rides in the same write. It is an application-level map, so it is collected from
        # every tab (MERGE-on-write in the container) instead of the active one overwriting the rest.
        for page in self._tab_pages():
            merge = getattr(getattr(page, "sftp_tab", None), "merge_dirs_into", None)
            if not callable(merge):
                continue
            try:
                merge(payload)
            except (RuntimeError, AttributeError):
                continue  # a teardown race — the other tabs still contribute
        if isinstance(extra, dict):
            extra.update(payload)
            return extra
        return payload

    def resizeEvent(self, event):
        """v1.3.3.5 (ROADMAP task 3a): a window resize re-applies the split geometry
        (the proportion is kept, the floors hold). The pane's own canvas resize — and
        therefore the PTY debounce — is handled inside the page (its eventFilter)."""
        super().resizeEvent(event)
        if self.split.on:
            self.split.apply_sizes()

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
        # v1.7.1.1: the per-WINDOW Files panel switch — the ONLY surface of the switch left
        # besides the settings hub's "Files display mode" key: a live override of this window
        # that is not persisted. The corner button is gone.
        act_panel = getattr(self, "act_files_panel", None)
        if act_panel is not None:
            menu.addAction(act_panel)
        # v1.7.2 (task 5): the MERGE — this window collects the sessions of the other ones. A
        # context-menu item only: the corner's budget is three labels (AGENTS.md §4.12) and the
        # action carries no registry sequence.
        act_merge = getattr(self, "act_merge", None)
        if act_merge is not None:
            menu.addSeparator()
            menu.addAction(act_merge)
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
        # v1.7.1: the Files panel follows the TAB STRIP (not the focus): the right-hand tree
        # is the tree of the session whose tab is current, with its own browsed directory and
        # its own viewer. Done BEFORE the split-pane branch below — a pane that holds the
        # keyboard must not freeze the tree of the tab the user just switched to.
        self._refresh_files_panel_current()
        # v1.7.2 (task 3): the split action mirrors the ACTIVE session and the window title names
        # it — re-read on EVERY tab change, before the focused-pane branch returns.
        self.split.sync_owner()
        self._refresh_window_title()
        # v1.3.3.5: the ACTIVE TAB is the fallback — while the keyboard focus sits in
        # the split pane, switching tabs does not steal the bridge from it.
        if self.focused_split_pane() is not None:
            self._refresh_bridge()
            return
        self._set_bridged_page(page)
        # v1.6.1 (ROADMAP task 8): the tab the user switched TO owns the keyboard, so a
        # fresh session is usable without a click on the canvas. Skipped in the branch
        # above — a pane that holds the keyboard keeps it. Duck-typed hook: a page that
        # cannot take the focus answers False and is left alone.
        claim = getattr(page, "claim_focus", None)
        if callable(claim):
            try:
                claim()
            except RuntimeError:
                pass  # Qt teardown (a close race)

    def _set_bridged_page(self, page):
        """Bridge of the ACTIVE tab's signals into the window's status bar
        (the v1.2 look); on tab switch — a reconnect: the status bar shows the
        active session, and inactive tabs' messages do not touch it. The SFTP
        progress bar syncs with the active tab's state (inactive transfers do
        not update the bar).

        v1.6.4 (ROADMAP task 4): the bridged page IS the session the user is looking at — the
        activity mark is cleared here, which is what makes a tab switch (and the focus moving
        into the split pane) clear it in ONE place. Idempotent.
        """
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
        # v1.6.4 (ROADMAP task 4): the visible session has no "new output" to announce.
        clear = getattr(page, "set_activity", None)
        if callable(clear):
            try:
                clear(False)
            except RuntimeError:
                pass  # Qt teardown — the page is already destroyed
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
        # v1.7rc1: the corner control follows the bridged (visible) session — the mode, the
        # label and the enabled state are the ACTIVE session's, never the window's.
        self._sync_commander()

    # ── v1.2: bridge "page status bar → window status bar" (look = v1.1.x) ───

    def _on_page_status_message(self, text: str, timeout_ms: int):
        try:
            if timeout_ms > 0:
                self.statusBar().showMessage(text, timeout_ms)
            else:
                self.statusBar().showMessage(text)
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)

    # ── v1.6.4 (ROADMAP task 4): the activity mark of an inactive session ────

    def session_is_visible(self, page) -> bool:
        """The container's answer to "is `page` the session on screen?" — the mark's ONE rule.

        The v1.3.3.5 "active session" rule of this window: the FOCUSED split pane wins over the
        active tab (with two shells on one screen the user's attention is where the keyboard
        is). A page this window never showed is not visible. Never raises.
        """
        pane = self.focused_split_pane()
        if pane is not None:
            return page is pane
        try:
            return self.session_tabs.currentWidget() is page
        except RuntimeError:
            return False

    def session_activity_changed(self, page):
        """Re-render ONE session's tab: the activity mark and its tooltip (idempotent)."""
        render_session_activity(self.session_tabs, page, get_translator())

    # ── v1.4.7 follow-up: the SECOND status text — the split pane ────────────

    def _on_split_status_message(self, text: str, _timeout_ms: int = 0):
        """The split pane's LIVE status → its own text in the status bar.

        The pane is a command line: it has no status line and no tab strip (it is a
        single-tab page), so its state is rendered HERE, right after the active
        session's message — `terminal.split` names the pane ("Split Terminal"), the
        same "name the real label" rule the empty state follows, which keeps this free
        of new i18n keys. An empty text hides the line. Never raises.
        """
        self._split_status_text = text or ""
        self._render_split_status()

    def _render_split_status(self):
        """Render (or hide) the split pane's status text in the current language.

        Split out of the handler so `retranslate()` can re-render the SAME text with
        the new `terminal.split` prefix while the line stays live. Never raises.
        """
        try:
            text = getattr(self, "_split_status_text", "")
            if not text:
                self._split_status_label.clear()
                self._split_status_label.hide()
                return
            self._split_status_label.setText(
                f"{get_translator()('terminal.split')}  {text}")
            self._split_status_label.show()
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)

    def _hide_split_status(self, pane=None):
        """Drop the pane's status text (the pane is closing) — idempotent, never raises."""
        if pane is not None:
            try:
                pane.status_message.disconnect(self._on_split_status_message)
            except (TypeError, RuntimeError):
                pass  # not connected / the C++ object was destroyed — nothing to drop
        self._on_split_status_message("", 0)

    @property
    def split_status_text(self) -> str:
        """The RAW state of the split pane as rendered in the status bar ("" — closed)."""
        return getattr(self, "_split_status_text", "")

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

    # ── v1.7.2 (tasks 5/6): the merge, the on-screen title and the remote title ──

    def _on_merge_windows(self, _checked=False):
        """`act_merge.triggered` → the host's merge of the other windows into THIS one.

        The registry and the "which window is a terminal window" question belong to the host
        (`SshMixin._merge_terminal_windows`, `ui/main_window_ssh.py`) — the window only asks,
        through the parent chain, so `modules/*` still imports no window module (§4.1).
        """
        sink = find_host_hook(self, "_merge_terminal_windows")
        if sink is None:
            return
        try:
            sink(self)
        except Exception:  # noqa: BLE001 — a merge failure must never break the window
            pass

    def tab_pages(self) -> list:
        """The sessions that CARRY A TAB, in tab order (the split pane is not one)."""
        try:
            pages = [self.session_tabs.widget(i) for i in range(self.session_tabs.count())]
        except RuntimeError:
            return []    # the C++ object was already destroyed (a close race)
        return [p for p in pages if p is not None]

    def take_session(self, page) -> bool:
        """Hand ONE tab session over to another container WITHOUT tearing it down.

        The page keeps its thread, its pyte screen, its scrollback, its command history, its
        transcript and its SFTP worker — a move is a RE-PARENTING, which is exactly what makes
        `Merge Windows` affordable. The Files widget goes back to its own tab strip first (the
        panel owns it while the mode is on) and the tab is removed WITHOUT the `close_page()`
        teardown. Never raises; False — the page is not a tab of this window.
        """
        try:
            index = self.session_tabs.indexOf(page)
        except RuntimeError:
            return False
        if index < 0:
            return False
        self._release_files_panel_page(page)
        self._commander_kept.pop(getattr(page, "sftp_tab", None), None)
        try:
            self.session_tabs.removeTab(index)
        except RuntimeError:
            return False
        try:
            page.setParent(None)
        except RuntimeError:
            pass
        return True

    def adopt_session(self, page) -> bool:
        """Take ONE session over from another container as the NEXT tab of this window."""
        if page is None:
            return False
        t = get_translator()
        try:
            page.setParent(self.session_tabs)
        except RuntimeError:
            return False
        page.set_host_window(self)
        self._wire_page(page)
        try:
            index = self.session_tabs.addTab(page, self._session_tab_title(page))
        except RuntimeError:
            return False
        render_session_activity(self.session_tabs, page, t)
        if self._files_panel_on:
            self._attach_files_panel_page(page)
        try:
            self.session_tabs.setCurrentIndex(index)
        except RuntimeError:
            pass
        return True

    def _session_tab_title(self, page) -> str:
        """The tab TEXT of a session — always the node alias (the remote title is the tooltip)."""
        data = getattr(page, "server_data", None)
        return str(getattr(data, "alias", "") or self.server_data.alias)

    def _title_page(self):
        """The session the window title NAMES — the one on screen (the focused pane wins)."""
        return self.page

    def _refresh_window_title(self):
        """Re-text the window title for the session ON SCREEN (the merged window's answer).

        A window that collects sessions cannot name the FIRST session any more: the base title is
        rebuilt from the session the keyboard is in (`terminal.window_title`), and the REMOTE title
        the program set over `OSC 0`/`OSC 2` is preferred when it exists — "SSH Terminal" then says
        which of the eight shells the user is looking at. The multi-input prefix is preserved
        (`_multi_base_title` keeps the base for `apply_container_highlight`). Never raises.
        """
        t = get_translator()
        page = self._title_page()
        data = getattr(page, "server_data", None) or getattr(self, "server_data", None)
        alias = str(getattr(data, "alias", "") or "?")
        host = str(getattr(data, "host", "") or "")
        remote = str(getattr(page, "remote_title", "") or "")
        base = t("terminal.window_title", alias=remote or alias, host=host)
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
            except Exception:  # noqa: BLE001 — the hub must not break the title
                prefixed = False
        self._multi_base_title = base
        try:
            self.setWindowTitle((t("terminal.multi_title_prefix") + base) if prefixed else base)
        except RuntimeError:
            pass   # the C++ object was already destroyed (a close race)

    def session_title_changed(self, page):
        """The remote program set a NEW title (`OSC 0`/`OSC 2`) — refresh the two surfaces.

        The tab TOOLTIP carries the remote title as its second line (the shipped second channel of
        the activity mark, re-rendered by the ONE shared helper) and the window title prefers it
        while `page` is the session on screen. Never raises.
        """
        try:
            render_session_activity(self.session_tabs, page, get_translator())
        except RuntimeError:
            pass   # Qt teardown — the tab strip is already gone
        if page is self._title_page():
            self._refresh_window_title()

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
        # The window's size/state is saved BEFORE the "ask" dialog — if the user cancels the close
        # (`event.ignore`), the written values are equal to the current ones anyway; on a normal close the
        # next window reads them. The split state/ratio ride along in the SAME `save_config()` call (merged
        # into the geometry write — one write per window).
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


