import socket
from typing import Dict, Optional
from PySide6.QtCore import QThread, Signal


# Cached translator for this module (loaded once on first call)
_t_cache = None

def _get_translator():
    """Safe i18n helper with caching — avoids repeated imports in hot path."""
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


# ── Registry of active workers ───────────────────
# server_id → running SSHWorker. Populated when the thread is created and cleared on the
# `finished()` signal: before removing a `ServerNode` we check that its SSH operation finished
# cleanly, otherwise the thread could deliver success/error to an already-destroyed dialog, or keep
# writing to the data of a removed node.
_active_workers: Dict[str, "SSHWorker"] = {}


def get_active_worker(server_id: str) -> Optional["SSHWorker"]:
    """The server's active (still running, not yet finished) SSHWorker, or None."""
    if not server_id:
        return None
    worker = _active_workers.get(server_id)
    if worker is None or worker.isFinished():
        return None
    return worker


def wait_for_worker(server_id: str, timeout_ms: int = 5000) -> bool:
    """Wait for the server's SSHWorker to finish.

    Returns True if there is no active thread (or it finished within
    timeout_ms). False — the thread is still running; the node should not
    be removed. Every operation inside the worker has internal network
    timeouts (socket 5 s / paramiko 15 s), so wait() cannot hang forever.
    """
    worker = get_active_worker(server_id)
    if worker is None:
        return True
    return bool(worker.wait(timeout_ms))


class SSHWorker(QThread):
    """One-shot thread for an SSH check/connection without blocking the UI."""

    success = Signal(str)
    error = Signal(str)

    def __init__(self, host: str, user: str, port: int, server_id: str = "",
                 password: str = "", key_path: str = "",
                 test_only: bool = False, load_from_store: bool = True,
                 parent=None):
        super().__init__(parent)
        # v1.6.4 (ROADMAP task 1): the MANAGED worker names itself. Qt's abort —
        # "QThread: Destroyed while thread '' is still running" — names NOTHING on an
        # unnamed thread, in a codebase whose orphan registry below exists to prevent
        # exactly that abort; the journal names the worker by this string. No behaviour.
        self.setObjectName("SSHWorker")
        self.host = host
        self.user = user
        self.port = port
        self.server_id = server_id  # for loading from the keyring
        self.password = password
        self.key_path = key_path
        self.test_only = test_only
        self.load_from_store = load_from_store

        # Register in the active worker registry (patch v0.6.x): the guard for
        # node removal. Auto-cleanup — on the thread's finished().
        if server_id:
            _active_workers[server_id] = self
            def _unregister(_=None, sid=server_id):
                if _active_workers.get(sid) is self:
                    del _active_workers[sid]
            self.finished.connect(_unregister)

    def run(self):
        try:
            if self.test_only:
                self._run_socket_test()
            else:
                self._run_ssh_connect()
        except Exception as e:
            self.error.emit(str(e))

    def _run_socket_test(self):
        t = _get_translator()
        try:
            with socket.create_connection((self.host, self.port), timeout=5):
                pass
            self.success.emit(t("ssh.socket_test_ok", host=self.host, port=self.port))
        except socket.timeout:
            # v0.9.3 fix: before this a hardcoded English string went here, bypassing i18n.
            self.error.emit(t("ssh.socket_timeout", host=self.host, port=self.port))
        except OSError as e:
            msg = t("ssh.connection_failed", host=self.host, port=self.port)
            # Fallback if translation unavailable (returns [key])
            self.error.emit(msg if not msg.startswith("[") else f"Connection failed for {self.host}:{self.port}: {e}")
        except Exception as e:
            self.error.emit(str(e))

    def _run_ssh_connect(self):
        import paramiko
        t = _get_translator()
        from services.credential_manager import get_credential_manager

        # v1.8rc6 (N50): the ONE connect builder (`AGENTS.md` §4.4) — the branch table, the
        # known-hosts policy and the single `connect()` live in `modules/ssh_connect.py`; this
        # site keeps only the credential resolution and the error reporting below.
        try:
            from .ssh_connect import CONNECT_TIMEOUT_S, connect_client
        except ImportError:  # flat layout
            from ssh_connect import CONNECT_TIMEOUT_S, connect_client

        # Resolve password: explicit arg > credential manager > key-based fallback
        final_password = self.password or ""
        if not final_password and self.server_id and self.load_from_store:
            cm = get_credential_manager()
            cached_pw = cm.load_password(self.server_id)
            if cached_pw:
                final_password = cached_pw

        # The client is built BEFORE the try so the `finally: client.close()` below always has one.
        client = paramiko.SSHClient()
        try:
            # v1.2.10 (AUDIT auto #1): the KEY branch passes the resolved password as a
            # FALLBACK — paramiko tries the key first and the password last. Before the fix
            # "Connect over SSH" failed where "Gather information" worked. v1.1.2RC1 (N5): the
            # PASSWORD branch passes look_for_keys=False/allow_agent=False, so no local key and
            # no agent is polled before the attempt.
            client, policy = connect_client(self.host, self.user, self.port,
                                            password=final_password, key_path=self.key_path,
                                            client=client, timeout=CONNECT_TIMEOUT_S)

            msg = t("ssh.connected_ok", host=self.host)
            # AUDIT v0.7.2 (high #4): first connection — warn about the accepted key
            if policy.accepted_new_key and policy.last_fingerprint:
                note = t("ssh.host_key_new", host=self.host, fp=policy.last_fingerprint)
                msg += "\n" + (note if not note.startswith("[") else f"New host key accepted ({policy.last_fingerprint})")
                if not policy.pinned:
                    # v1.7.5.1 (N48): an unreadable store remembers nothing — say so.
                    warn = t("ssh.host_key_unpinned", path=policy.store.path)
                    msg += "\n" + (warn if not warn.startswith("[")
                                   else "WARNING: host key NOT saved")
            self.success.emit(msg if not msg.startswith("[") else f"✓ Connected to {self.host}")
        except paramiko.BadHostKeyException as e:
            # AUDIT v0.7.2 (high #4): the stored host key changed — a likely MITM
            try:
                from modules.logger import get_logger as _gl
                _gl("modules.ssh_worker").warning(f"Host key mismatch for {self.host}: {e}")
            except Exception:
                pass
            msg = t("ssh.host_key_changed", host=self.host) + "\n" + str(e)
            self.error.emit(msg if not msg.startswith("[") else f"Host key changed for {self.host}: {e}")
        except paramiko.AuthenticationException:
            msg = t("ssh.auth_failed")
            self.error.emit(msg if not msg.startswith("[") else "Authentication failed")
        except paramiko.SSHException as e:
            msg = t("ssh.ssh_error", message=str(e))
            self.error.emit(msg if not msg.startswith("[") else f"SSH error: {e}")
        except OSError as e:
            # `socket.gaierror`, `socket.timeout` and `paramiko.ssh_exception.NoValidConnectionsError` are
            # OSError, NOT SSHException — they would otherwise fall through to the generic handler of `run()`
            # and be displayed VERBATIM in English while the sibling "Test connection" button answered in the
            # user's language. The branch is deliberately LAST so it cannot shadow the paramiko ones above.
            msg = t("ssh.connection_failed", host=self.host, port=self.port)
            self.error.emit(msg if not msg.startswith("[")
                            else f"Connection failed for {self.host}:{self.port}: {e}")
        finally:
            client.close()
