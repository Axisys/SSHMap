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

v1.5.3 (ROADMAP task 3): the module also owns the **reachability report** — the "why is
it red?" answer behind a red card. `diagnose_reachability()` runs the steps the
application already knows how to take, IN ORDER — DNS resolve → TCP connect → SSH
banner → ICMP ping — and names the FIRST step that failed in its own words; `ReachabilityThread`
is the off-the-GUI-thread wrapper. The report is a `ReachabilityReport` (a frozen
dataclass of FACTS — no i18n, no Qt), and `report_parts()` turns it into the
`(i18n key, params)` pairs the window formats: this module stays language-free exactly
like `status_checker.probe_ssh`, and the STATUS itself is never touched — a report
explains, it does not decide.
"""
import platform
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
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


# ── v1.5.3 (ROADMAP task 3): the reachability report — "why is it red?" ────────────
# A red card collapses refused / timeout / DNS into ONE `offline`
# (`status_checker.probe_ssh`), and that is exactly the moment a user needs the
# difference. The pieces of the real answer already exist in this module and in the
# probe; the release only puts them in ORDER and names the FIRST step that failed.
#
# The steps are DECLARED (REPORT_STEP_ORDER) and the verdict of the first failure is a
# KIND (one i18n key each) — so the report is data, and the sentence is composed by the
# window (`report_parts()`), which keeps this module free of i18n and Qt-free logic
# (`probe_ssh` has the same shape: a fact out, the words elsewhere).
#
# Budget: every network step keeps the 3 s probe budget (`REPORT_TIMEOUT_S`); a report
# runs at most DNS + TCP + one ICMP packet, so it is bounded by ~2 × timeout + the ping's
# own timeout — it is an EXPLICIT user action (a context-menu item), never a periodic one.

REPORT_TIMEOUT_S = 3.0                 # a single step's budget (the probe's own 3 s)
PING_BUDGET_S = 4.0                    # the ICMP stage: 1 packet + a 4 s ceiling
BANNER_BYTES = 32                      # what probe_ssh reads (and what we read here)
BANNER_MAX_CHARS = 40                  # the banner text a sentence may quote
DNS_THREAD_NAME = "sshmap-dns-report"  # the daemon thread of a bounded lookup

#: The steps, in the order the report runs them (the acceptance of the task).
REPORT_STEP_ORDER = ("dns", "tcp", "banner", "ping")

#: The verdicts. `ok` — the host is an SSH server; everything else names the FIRST
#: failing step, and one `diagnose.<kind>` key is its sentence.
KIND_OK = "ok"
KIND_DNS_FAILED = "dns_failed"
KIND_DNS_TIMEOUT = "dns_timeout"
KIND_TCP_REFUSED = "tcp_refused"
KIND_TCP_TIMEOUT = "tcp_timeout"
KIND_TCP_FAILED = "tcp_failed"
KIND_BANNER_SILENT = "banner_silent"
KIND_BANNER_FOREIGN = "banner_foreign"

#: kind → the step it belongs to (the report answers "which step failed", not only "what").
KIND_STEP = {
    KIND_OK: "",
    KIND_DNS_FAILED: "dns",
    KIND_DNS_TIMEOUT: "dns",
    KIND_TCP_REFUSED: "tcp",
    KIND_TCP_TIMEOUT: "tcp",
    KIND_TCP_FAILED: "tcp",
    KIND_BANNER_SILENT: "banner",
    KIND_BANNER_FOREIGN: "banner",
}

#: Every verdict a report can carry (the topical test pins the SET, so a new kind
#: cannot appear without joining it — and the language files with it).
REPORT_KINDS = (KIND_OK, KIND_DNS_FAILED, KIND_DNS_TIMEOUT, KIND_TCP_REFUSED,
                KIND_TCP_TIMEOUT, KIND_TCP_FAILED, KIND_BANNER_SILENT,
                KIND_BANNER_FOREIGN)


@dataclass(frozen=True)
class ReachabilityReport:
    """The FACTS of one on-demand reachability report (v1.5.3, ROADMAP task 3).

    Frozen and language-free: the harness asserts the four acceptance scenarios on it
    without a window, and the text lives in the i18n keys `report_parts()` names.
    """

    host: str
    port: int = 22
    kind: str = KIND_OK
    ip: str = ""          # the address DNS answered with ("" — DNS failed)
    detail: str = ""      # the technical detail: the error text, the foreign banner, the SSH banner
    ping: str = ""        # "" — not attempted | "ok" | "failed"
    timeout: float = REPORT_TIMEOUT_S
    elapsed: float = 0.0
    steps: tuple = field(default=())   # (step, kind) in the order they really ran

    @property
    def ok(self) -> bool:
        """Did every step succeed (the host really speaks SSH)?"""
        return self.kind == KIND_OK

    @property
    def step(self) -> str:
        """The FIRST step that failed ("" — none: the host answered)."""
        return KIND_STEP.get(self.kind, "")

    @property
    def i18n_key(self) -> str:
        """The i18n key of the verdict's sentence (`diagnose.<kind>`)."""
        return f"diagnose.{self.kind}"


def _short(text: str, limit: int = BANNER_MAX_CHARS) -> str:
    """A one-line, printable, bounded form of a piece of remote/protocol text."""
    clean = "".join(ch for ch in str(text or "") if ch.isprintable())
    clean = " ".join(clean.split())
    return clean[:limit]


def resolve_host(host: str, timeout: float = REPORT_TIMEOUT_S):
    """Resolve a name in a bounded way: `(ip, error)` — "" error means success.

    `socket.getaddrinfo` takes no timeout, and a broken resolver is exactly the case this
    report exists for, so the lookup runs on a DAEMON thread the report waits on for
    `timeout` seconds and then abandons ("timeout"): the daemon flag keeps a hung
    resolver from holding the process at exit (the orphan-thread discipline, without the
    QThread half — there is no C++ object to destroy here).
    """
    target = str(host or "").strip()
    if not target:
        return "", "empty host"
    box: dict = {}

    def _worker():
        try:
            box["infos"] = socket.getaddrinfo(target, None)
        except Exception as exc:  # noqa: BLE001 — a broken name is the ANSWER here
            box["error"] = str(exc) or exc.__class__.__name__

    thread = threading.Thread(target=_worker, name=DNS_THREAD_NAME, daemon=True)
    thread.start()
    thread.join(max(0.1, float(timeout)))
    if thread.is_alive():
        return "", "timeout"
    if box.get("error"):
        return "", box["error"]
    for info in box.get("infos") or ():
        try:
            address = info[4][0]
        except (IndexError, TypeError):
            continue
        if address:
            return str(address), ""
    return "", "no address"


def ping_once(host: str, timeout: float = PING_BUDGET_S) -> bool:
    """ONE ICMP packet — the LAST step of a report (True = the host answered).

    Deliberately not `PingThread` (3 packets, the IPC message of the status bar): the
    report uses one packet with the same -w/-W budget discipline, because its job is
    "does the host answer at all", not "how good is the link". A host starting with "-"
    is refused BEFORE a process is launched (the v1.2.10rc2 lesson: Windows `ping` takes
    no `--`, so an argument-shaped host would be eaten as a flag).
    """
    target = str(host or "").strip()
    if not target or target.startswith("-"):
        return False
    seconds = max(0.2, float(timeout))
    if platform.system() == "Windows":
        cmd = ["ping", "-n", "1", "-w", str(int(seconds * 1000)), target]
    else:
        cmd = ["ping", "-c", "1", "-W", str(max(1, int(round(seconds)))), "--", target]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=seconds + 2.0,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if platform.system() == "Windows" else 0)
    except Exception:  # noqa: BLE001 — no ping binary / a hung process: "no answer"
        return False
    return proc.returncode == 0


def diagnose_reachability(host: str, port: int = 22, timeout: float = REPORT_TIMEOUT_S,
                          *, resolver=None, connector=None, pinger=None) -> ReachabilityReport:
    """Run DNS → TCP → SSH banner (→ ICMP ping) and report the FIRST failure.

    The three callables are the TEST SEAMS (the status provider / transport injection
    pattern of the plugin runner): `resolver(host, timeout) -> (ip, error)`,
    `connector(host, port, timeout) -> (sock, error)` and `pinger(host, budget) -> bool`.
    Production passes the defaults (`resolve_host` / `_connect` / `ping_once`), so a test
    can produce a DNS-only failure, a refused port, a silent port and a live SSH host
    WITHOUT a network — which is exactly the task's acceptance list.

    The ICMP step runs only when TCP failed: after a banner the host is proven alive, and
    before DNS there is nothing to ping. Its result is EVIDENCE, not a verdict — the
    first failing step keeps the headline.
    """
    started = time.monotonic()
    resolver = resolver or resolve_host
    connector = connector or _connect
    pinger = pinger or (lambda target, budget: ping_once(target, budget))
    host = str(host or "").strip()
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = 22
    port = max(1, min(65535, port))
    budget = max(0.2, float(timeout))
    steps = []

    def _report(kind, ip="", detail="", ping="", banner=""):
        steps.append((KIND_STEP.get(kind, ""), kind))
        return ReachabilityReport(
            host=host, port=port, kind=kind, ip=ip,
            detail=_short(banner or detail), ping=ping, timeout=budget,
            elapsed=time.monotonic() - started, steps=tuple(steps))

    # ── step 1: DNS ────────────────────────────────────────────────────────────
    try:
        ip, error = resolver(host, budget)
    except Exception as exc:  # noqa: BLE001 — a broken resolver seam is "DNS failed"
        ip, error = "", str(exc)
    ip = str(ip or "")
    error = str(error or "")
    if not ip:
        kind = KIND_DNS_TIMEOUT if error == "timeout" else KIND_DNS_FAILED
        return _report(kind, detail=error)

    # ── step 2: TCP ────────────────────────────────────────────────────────────
    sock, tcp_error = None, ""
    try:
        sock, tcp_error = connector(ip, port, budget)
    except Exception as exc:  # noqa: BLE001 — a broken connector seam is a TCP failure
        sock, tcp_error = None, str(exc)
    if sock is None:
        kind = _TcpError.kind_for(tcp_error)
        # "Is it the port or the host?" — the ONE question ICMP can still answer.
        answered = False
        try:
            answered = bool(pinger(host, budget))
        except Exception:  # noqa: BLE001 — a report never raises
            answered = False
        return _report(kind, ip=ip, detail=tcp_error,
                       ping="ok" if answered else "failed")

    # ── step 3: the SSH banner ─────────────────────────────────────────────────
    try:
        try:
            banner_bytes = sock.recv(BANNER_BYTES)
        except (socket.timeout, TimeoutError, OSError):
            return _report(KIND_BANNER_SILENT, ip=ip)
        if not banner_bytes:
            return _report(KIND_BANNER_SILENT, ip=ip)
        banner = banner_bytes.decode("utf-8", errors="replace").strip()
        if not banner.lstrip().startswith("SSH-"):
            return _report(KIND_BANNER_FOREIGN, ip=ip, banner=banner)
        return _report(KIND_OK, ip=ip, banner=banner)
    finally:
        try:
            sock.close()
        except Exception:  # noqa: BLE001 — closing a probe socket is best-effort
            pass


class _TcpError:
    """Which verdict a failed TCP connect deserves (the only place that decides it)."""

    @staticmethod
    def kind_for(error: str) -> str:
        text = str(error or "").lower()
        if "refused" in text:
            return KIND_TCP_REFUSED
        if "timed out" in text or "timeout" in text:
            return KIND_TCP_TIMEOUT
        if not text:
            return KIND_TCP_TIMEOUT
        return KIND_TCP_FAILED


def _connect(host: str, port: int, timeout: float):
    """The production connector: `(socket, error)` — never raises, always closes nothing."""
    try:
        return socket.create_connection((host, port), timeout=timeout), ""
    except Exception as exc:  # noqa: BLE001 — the error TEXT is what classifies it
        return None, str(exc) or exc.__class__.__name__


def report_parts(report: ReachabilityReport) -> list:
    """The `(i18n key, params)` pairs of a report: the verdict first, the ICMP evidence second.

    PURE (no i18n import): the window formats the pairs with `t()` — which keeps the
    words in the language files and the logic testable without a window. The params of a
    kind are the placeholders its sentence uses; an extra one is harmless (`t()` ignores
    what the sentence does not mention).
    """
    key = report.i18n_key
    params = {"host": report.host, "port": report.port}
    if report.kind == KIND_OK:
        params["banner"] = report.detail
    elif report.kind in (KIND_DNS_FAILED, KIND_DNS_TIMEOUT):
        pass
    else:
        params["ip"] = report.ip or report.host
    if report.kind == KIND_TCP_TIMEOUT:
        params["timeout"] = f"{float(report.timeout):g}"
    if report.kind in (KIND_TCP_FAILED, KIND_BANNER_FOREIGN):
        params["banner" if report.kind == KIND_BANNER_FOREIGN else "detail"] = report.detail
    parts = [(key, params)]
    if report.ping == "ok":
        parts.append(("diagnose.ping_ok", {"host": report.host}))
    elif report.ping == "failed":
        parts.append(("diagnose.ping_failed", {"host": report.host}))
    return parts


class ReachabilityThread(QThread):
    """One reachability report on a worker thread (v1.5.3, ROADMAP task 3).

    The report blocks on DNS/TCP/banner and may launch a `ping` process, so it never runs
    on the GUI thread (§4.8). One thread per request, owned by the window's registry (the
    `_ping_thread` pattern); `report_ready(server_id, ReachabilityReport)` carries the
    FACTS, and the window composes and routes the sentence.
    """

    report_ready = Signal(str, object)

    def __init__(self, server_id: str, host: str, port: int = 22,
                 timeout: float = REPORT_TIMEOUT_S, parent=None, **seams):
        super().__init__(parent)
        self._server_id = str(server_id)
        self._host = host
        self._port = port
        self._timeout = timeout
        self._seams = seams   # resolver / connector / pinger — the test seam

    def run(self):
        try:
            report = diagnose_reachability(self._host, self._port, self._timeout,
                                           **self._seams)
        except Exception as exc:  # noqa: BLE001 — a report must never kill the thread
            report = ReachabilityReport(host=str(self._host), port=int(self._port or 22),
                                        kind=KIND_TCP_FAILED, detail=str(exc))
        try:
            self.report_ready.emit(self._server_id, report)
        except RuntimeError:
            pass  # the receiver died with its window — the report is simply dropped

