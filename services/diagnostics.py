"""Background diagnostics of map nodes: ping + reverse DNS (v0.9.9.3).

The classes were moved in v0.9.9.3 FROM ui/main_window.py, where they were
nested directly in the `_ping_node` / `_copy_node_info` methods (phase 0 of the
"main_window.py hygiene" series). ZERO behavior change: the same signals, the
same ping command lines, the same i18n keys, the same fallback to host on a
DNS failure.

The "module + callbacks" pattern: MainWindow holds references to the threads
(`self._ping_thread` / `self._dns_thread` — guard AUDIT v0.7.2 #8 against
clobbering a running ping and orphan threads), connects the signals
with local closures as callbacks and starts the thread; the stop on window
close — the shared `_shutdown_background_threads()` (stop()/wait(), like StatusChecker).

Usage (MainWindow):
    from services.diagnostics import PingThread, ReverseDnsThread

    ping = PingThread(host)
    ping.finished_ping.connect(on_done)      # (ok: bool, text: str)
    self._ping_thread = ping                 # keep the reference — not an orphan
    ping.start()

    dns = ReverseDnsThread(host, parent=self)  # v1.2.10rc1: parent — owner of the C++ object
    dns.resolved.connect(on_resolved)        # (name: str)
    self._dns_thread = dns
    dns.start()

v1.2.10rc1 (AUDIT auto #2 + a verification finding): the orphan-thread registry
`_orphan_threads` + `register_orphan_thread()` — ping/DNS have no stop(), and with
an unreachable resolver getaddrinfo/ping outlive the shutdown wait budget
(~2 s); a surviving thread must not be left to GC ("QThread: Destroyed while thread
is still running") — the registry holds it until finished() (pattern N4, _orphan_threads
from modules/ssh_terminal.py).
"""
import platform
import subprocess
from typing import List

from PySide6.QtCore import QThread, Signal


# ── v1.2.10rc1: orphan-thread registry for ping/DNS (pattern N4) ───────────────────
# PingThread/ReverseDnsThread have NO stop(): on window close we can only
# wait for them with a budget (~2 s, MainWindow._shutdown_background_threads).
# If getaddrinfo/ping outlive the budget (an unreachable resolver — exactly the
# scenario for which DNS was moved to a thread), a live QThread with no strong
# referencing object must not be left to GC: "QThread: Destroyed while thread
# is still running" + the risk of a RuntimeError on late emits. The registry holds
# such threads until finished() — like _orphan_threads (modules/ssh_terminal.py,
# v1.1.2RC1 N4); all window slots are already disconnected / the window is closed
# by then, so late emits without receivers — a safe no-op.
_orphan_threads: List["QThread"] = []


def register_orphan_thread(thread: "QThread"):
    """Hold a still-running ping/DNS thread until finished() (v1.2.10rc1).

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


class PingThread(QThread):
    """Ping a node in a separate thread without blocking the GUI (v0.7.3).

    Windows: `ping -n 3`, POSIX: `ping -c 3`. The result — the finished_ping
    signal; interpretation (status bar / dialog) is left to the calling callback.
    """

    finished_ping = Signal(bool, str)

    def __init__(self, host):
        super().__init__()
        self._host = host

    def run(self):
        try:
            from i18n import t as _t
        except Exception:
            def _t(key, **kw):
                return key.format(**kw) if kw else key
        # v1.2.10rc2 (AUDIT manual #5d): guard BEFORE the subprocess — the Windows ping
        # does NOT support "--" (asymmetry of the branches: the POSIX command below has
        # it), so a host starting with "-" could be eaten as a flag. Such a host is
        # invalid as a DNS name anyway — we refuse WITHOUT launching the process (on both OSes).
        if isinstance(self._host, str) and self._host.startswith("-"):
            self.finished_ping.emit(False, _t("status.ping_failed", host=self._host))
            return
        count_flag = "-n" if platform.system() == "Windows" else "-c"
        # AUDIT v0.9.5.5 (security #4): -w/-W — milliseconds on Windows,
        # seconds on Linux; a 3 s timeout in both cases. On Linux the "--" before
        # the host, so a host of the form "-x" is not eaten as a flag.
        if platform.system() == "Windows":
            cmd = ["ping", count_flag, "3", "-w", "3000", self._host]
        else:
            cmd = ["ping", "-c", "3", "-W", "3", "--", self._host]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if platform.system() == "Windows" else 0)
            ok = proc.returncode == 0
            key = "status.ping_ok" if ok else "status.ping_failed"
            msg = _t(key, host=self._host)
            out = proc.stdout.decode(errors="replace")[-400:] if not ok else ""
            self.finished_ping.emit(ok, msg + ("\n" + out if out else ""))
        except Exception as exc:
            self.finished_ping.emit(False, _t("status.ping_failed", host=self._host)
                                    + f" ({exc})")


class ReverseDnsThread(QThread):
    """Reverse DNS outside the GUI thread (AUDIT v0.7.2, medium #6).

    With an unreachable resolver gethostbyaddr used to freeze on the DNS timeout
    in the GUI thread; now — a separate thread, the resolved(name) signal.
    DNS did not return a name → name = the host itself (the callback copies it as-is).
    """

    resolved = Signal(str)

    def __init__(self, host_, parent=None):
        # v1.2.10rc1 (AUDIT auto #2): parent — the QObject owner of the thread's C++ object
        # (MainWindow passes self): while the window is alive, the thread cannot be destroyed
        # by GC regardless of the Python references; a thread that outlives the shutdown
        # wait budget is registered in _orphan_threads above (register_orphan_thread).
        super().__init__(parent)
        self._host = host_

    def run(self):
        import socket as _socket
        try:
            name = _socket.gethostbyaddr(self._host)[0]
        except Exception:
            name = self._host  # DNS did not return a name — copy the host itself
        self.resolved.emit(name)
