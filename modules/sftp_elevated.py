# -*- coding: utf-8 -*-
"""The ELEVATED provider of a Files pane — a server read as ANOTHER user (`sudo`).

`ElevatedHandshake` opens ONE session channel over the transport the Files tab already rides,
pre-checks every `SFTP_SERVER_CANDIDATES` entry with `sudo -n -l`, primes the sudo timestamp on a
SEPARATE channel when a password was typed, and wraps the server the target user may run in
`paramiko.SFTPClient(channel)` — the pane's provider is then the SHIPPED `modules/sftp_worker`
over that client (one engine, a third CLIENT). The pure half owns the candidate list, the command
builders, the target-user allowlist and the machine codes the pane renders.
Contract — `ELEVATED_PANE.md`; mechanism — `DOCUMENTATION.md` §70."""

import re
import time
from typing import Optional

from PySide6.QtCore import QThread, Signal

try:
    from .logger import get_logger
except ImportError:
    try:
        from modules.logger import get_logger
    except ImportError:  # pragma: no cover — a stripped build logs nowhere
        import logging

        def get_logger(name):  # noqa: N802 — the same signature
            return logging.getLogger(name)

try:  # the client is created through the MODULE attribute, so a suite substitutes it
    import paramiko
except ImportError:  # pragma: no cover — a build without the SSH library
    paramiko = None

log = get_logger(__name__)

#: The candidate server binaries, in the order they are tried (`ELEVATED_PANE.md` §2). A host
#: answers with the FIRST one `sudo -n -l` permits AND that really completes the SFTP handshake.
SFTP_SERVER_CANDIDATES = (
    "/usr/lib/openssh/sftp-server",
    "/usr/libexec/openssh/sftp-server",
    "/usr/libexec/sftp-server",
    "/usr/lib/ssh/sftp-server",
    "/usr/local/libexec/sftp-server",
)

#: The target user of the elevation: a login name, never an option (`-u -evil` is an injection)
#: and never a metacharacter — the value reaches a FOREIGN parser on the other side of the channel.
ELEVATED_USER_RE = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_.\-]{0,31}$")

#: The bounded wait for ONE command's exit status and the poll step between two checks.
ELEVATION_WAIT_SEC = 6.0
ELEVATION_POLL_SEC = 0.02

#: How much of the server's own text a refusal carries (`ELEVATED_PANE.md` §2).
ELEVATION_DETAIL_CHARS = 200

#: The budget the pane waits for a stuck handshake before it is registered as an ORPHAN.
ELEVATED_SHUTDOWN_WAIT_MS = 2500

# The machine codes of a failed elevation (`ELEVATED_PANE.md` §6) — the pane owns the sentence.
ELEVATED_NO_TRANSPORT = "no_transport"
ELEVATED_PASSWORD = "password"
ELEVATED_REFUSED = "refused"
ELEVATED_OPEN_FAILED = "open_failed"
ELEVATED_FAILED = "failed"

# The i18n key of every code, declared ONCE so a code cannot ship without a sentence.
ELEVATED_ERROR_KEYS = {
    ELEVATED_NO_TRANSPORT: "sftp.elevated.no_transport",
    ELEVATED_PASSWORD: "sftp.elevated.password_refused",
    ELEVATED_REFUSED: "sftp.elevated.refused",
    ELEVATED_OPEN_FAILED: "sftp.elevated.open_failed",
    ELEVATED_FAILED: "sftp.elevated.failed",
}


def user_problem(user: str) -> Optional[str]:
    """Is this sudo target USER usable on a foreign command line? PURE — the reason, or None.

    An EMPTY user is legal and means `root` (the shipped `sudo -n <sftp-server>` form). A leading
    `-` is refused on its own: `sudo -n -u -evil` would hand the value to sudo's OWN option parser.
    """
    text = str(user or "").strip()
    if not text:
        return None
    if text.startswith("-"):
        return "option"
    if not ELEVATED_USER_RE.match(text):
        return "characters"
    return None


def sudo_prefix(user: str) -> str:
    """PURE: the `sudo -n` invocation that reaches the target user (`root` needs no `-u`)."""
    text = str(user or "").strip()
    if not text or text == "root":
        return "sudo -n"
    return "sudo -n -u %s" % (text,)


def elevated_server_command(user: str, binary: str) -> str:
    """PURE: the command the elevated channel runs — `sudo -n [-u <user>] <sftp-server>`."""
    return "%s %s" % (sudo_prefix(user), str(binary or ""))


def elevated_probe_command(user: str, binary: str) -> str:
    """PURE: the PRE-FLIGHT permission check — `sudo -n [-u <user>] -l <sftp-server>`."""
    return "%s -l %s" % (sudo_prefix(user), str(binary or ""))


def sudo_prime_command() -> str:
    """PURE: the priming of the sudo timestamp — the password arrives on STDIN, never in argv."""
    return "sudo -S -v"


def short_detail(text, limit: int = ELEVATION_DETAIL_CHARS) -> str:
    """PURE: ONE bounded line of a server's own text — what a refusal may show about itself."""
    folded = " ".join(str(text or "").split())
    return folded[:limit]


def _close_quiet(obj) -> bool:
    """Best-effort close of a channel or a client (never masks the real answer)."""
    if obj is None:
        return False
    try:
        obj.close()
        return True
    except Exception:  # noqa: BLE001 — a channel that is already gone is closed enough
        return False


def _read_stderr(chan, limit: int = ELEVATION_DETAIL_CHARS) -> str:
    """The bounded stderr of a command that just ended (sudo's own words, never a secret)."""
    try:
        if hasattr(chan, "recv_stderr_ready") and not chan.recv_stderr_ready():
            return ""
        data = chan.recv_stderr(4096)
    except Exception:  # noqa: BLE001 — an unreadable stream costs the detail, not the answer
        return ""
    if isinstance(data, bytes):
        data = data.decode("utf-8", "replace")
    return short_detail(data, limit)


# ── Orphan registry (the `register_orphan_sftp_worker` pattern, AGENTS.md §4.8) ──
_orphan_handshakes = []


def register_orphan_handshake(handshake) -> None:
    """Hold a still-running handshake until finished() (idempotent, detached from its parent)."""
    if handshake in _orphan_handshakes:
        return
    try:
        handshake.setParent(None)
    except RuntimeError:
        pass  # the C++ object is already gone
    _orphan_handshakes.append(handshake)

    def _drop(_=None, h=handshake):
        try:
            _orphan_handshakes.remove(h)
        except ValueError:
            pass  # already removed
    handshake.finished.connect(_drop)


class ElevatedHandshake(QThread):
    """ONE thread: the probe, the prime and the elevated `SFTPClient` (`ELEVATED_PANE.md` §2).

    `ready` carries the client AND the server's own answer for the directory the elevated session
    starts in; `failed` carries a MACHINE code and a short detail. The password lives on this
    object only until `run()` returns — a secret is never stored past the handshake.
    """

    ready = Signal(object, str)     # the paramiko SFTPClient, its start directory
    failed = Signal(str, str)       # a machine code, a short detail

    def __init__(self, transport, user: str = "", password: str = "", parent=None):
        super().__init__(parent)
        # A managed QThread carries a NAME (AGENTS.md §4.8): a bare '' in Qt's abort message is a
        # thread that never went through a constructor.
        self.setObjectName("ElevatedHandshake")
        self._transport = transport
        self._user = str(user or "")
        self._password = str(password or "")
        self._client = None
        self._channel = None

    # ── Public API (GUI thread) ──────────────────────────────────────────

    @property
    def user(self) -> str:
        """The target user this handshake was asked for."""
        return self._user

    def close(self):
        """Drop what this handshake opened (the pane is going away). Never raises."""
        client, channel = self._client, self._channel
        self._client = None
        self._channel = None
        _close_quiet(client)     # closing the client closes the channel it was built on
        _close_quiet(channel)
        self._password = ""

    def shutdown(self, wait_ms: int = ELEVATED_SHUTDOWN_WAIT_MS):
        """Cancel-free stop: wait ≤ wait_ms and register a stuck thread as an ORPHAN."""
        try:
            if self.isRunning():
                self.wait(wait_ms)
        except RuntimeError:
            return   # the C++ object is already gone
        if self.isRunning():
            register_orphan_handshake(self)

    # ── The handshake (worker thread) ────────────────────────────────────

    def run(self):
        try:
            self._handshake()
        except Exception as exc:  # noqa: BLE001 — a refusal is an answer, never a traceback
            self._emit(self.failed, ELEVATED_FAILED, short_detail(exc))
        finally:
            self._password = ""   # AGENTS.md §4.4: the secret does not outlive the attempt

    def _handshake(self):
        transport = self._transport
        if not self._live(transport):
            self._emit(self.failed, ELEVATED_NO_TRANSPORT, "")
            return
        code, detail = self._prime(transport)
        if code:
            self._emit(self.failed, code, detail)
            return
        client, channel, detail = self._open_server(transport)
        if client is None:
            self._emit(self.failed, ELEVATED_REFUSED, detail)
            return
        directory = self._start_dir(client)
        # The client is HANDED OVER with the answer: `close()` must never close the connection the
        # receiver is about to list through.
        self._client = None
        self._channel = None
        self._emit(self.ready, client, directory)

    @staticmethod
    def _live(transport) -> bool:
        """Is there a live transport to open a channel on?"""
        if transport is None:
            return False
        try:
            return bool(transport.is_active())
        except Exception:  # noqa: BLE001 — an unaskable transport is not a live one
            return False

    def _prime(self, transport):
        """Refresh the sudo timestamp on its OWN channel; `("", "")` — the gate is open.

        `sudo -S -v` reads the password from STDIN, and STDIN of this channel is nothing else: the
        SFTP channel of §2 never carries it. A refused password answers `ELEVATED_PASSWORD` with
        sudo's own bounded text, which never contains the secret it is complaining about.
        """
        if not self._password:
            return "", ""
        try:
            chan = transport.open_session()
        except Exception as exc:  # noqa: BLE001 — a dead transport is a declared refusal
            return ELEVATED_OPEN_FAILED, short_detail(exc)
        try:
            chan.exec_command(sudo_prime_command())
            try:
                chan.sendall((self._password + "\n").encode("utf-8"))
            except Exception:  # noqa: BLE001 — the command may already have refused it
                pass
            status = self._wait_exit(chan)
            detail = _read_stderr(chan)
        finally:
            _close_quiet(chan)
        if status == 0:
            return "", ""
        return ELEVATED_PASSWORD, detail

    def _open_server(self, transport):
        """`(client, channel, detail)` of the first candidate that answers; `(None, None, detail)`."""
        detail = ""
        for binary in SFTP_SERVER_CANDIDATES:
            code, text = self._allowed(transport, binary)
            if code:
                detail = text or detail
                continue
            client, channel, text = self._wrap(transport, binary)
            if client is not None:
                return client, channel, ""
            detail = text or detail
        return None, None, detail

    def _allowed(self, transport, binary: str):
        """Ask the host whether `sudo -n -l <binary>` is permitted: `("", "")` — yes."""
        try:
            chan = transport.open_session()
        except Exception as exc:  # noqa: BLE001 — a dead transport is a declared refusal
            return ELEVATED_OPEN_FAILED, short_detail(exc)
        try:
            chan.exec_command(elevated_probe_command(self._user, binary))
            status = self._wait_exit(chan)
            detail = _read_stderr(chan)
        finally:
            _close_quiet(chan)
        if status == 0:
            return "", ""
        return ELEVATED_REFUSED, detail

    def _wrap(self, transport, binary: str):
        """Open the real channel and wrap it: `(client, channel, detail)` — a failure names itself."""
        try:
            chan = transport.open_session()
        except Exception as exc:  # noqa: BLE001 — a dead transport is a declared refusal
            return None, None, short_detail(exc)
        try:
            chan.exec_command(elevated_server_command(self._user, binary))
        except Exception as exc:  # noqa: BLE001 — the exec itself was refused
            _close_quiet(chan)
            return None, None, short_detail(exc)
        mod = paramiko   # resolved at CALL time: the suite substitutes the module attribute
        client_cls = getattr(mod, "SFTPClient", None) if mod is not None else None
        if client_cls is None:
            _close_quiet(chan)
            return None, None, ""
        try:
            client = client_cls(chan)
        except Exception as exc:  # noqa: BLE001 — a permitted path that does not speak SFTP
            _close_quiet(chan)
            return None, None, short_detail(exc)
        return client, chan, ""

    def _wait_exit(self, chan) -> int:
        """The exit status of a finished command, bounded (a hung command is NOT a working one)."""
        deadline = time.monotonic() + ELEVATION_WAIT_SEC
        while time.monotonic() < deadline:
            try:
                if chan.exit_status_ready():
                    return int(chan.recv_exit_status())
            except Exception:  # noqa: BLE001 — an unaskable channel answers "not zero"
                return -1
            time.sleep(ELEVATION_POLL_SEC)
        return -1

    @staticmethod
    def _start_dir(client) -> str:
        """The server's OWN answer for the elevated session's directory (`/` — it did not say)."""
        try:
            resolved = str(client.normalize(".") or "")
        except Exception:  # noqa: BLE001 — a server that cannot resolve "." still lists
            return "/"
        return resolved if resolved.startswith("/") else "/"

    def _emit(self, signal, *args):
        """Emit with the teardown guard: a late emit without receivers is a safe no-op."""
        try:
            signal.emit(*args)
        except RuntimeError:
            pass
