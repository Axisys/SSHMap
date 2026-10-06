# -*- coding: utf-8 -*-
"""SSH host key policy — the answer to the MITM risk of `paramiko.AutoAddPolicy()` (AGENTS.md §4.4).

The application keeps its OWN known_hosts store in `~/.sshmap/known_hosts`: a key the store does not
know is SHOWN to the user (algorithm + SHA256 fingerprint, through `modules/interactive_ask.py`) and
pinned only when it is accepted, and a key that differs from the stored one raises through paramiko and
is offered as a REPLACE. Without an interactive surface the shipped TOFU accept applies, which is the
declared fallback of `interactive_ask.ask()`.

The store has ONE owner, `KnownHostsStore`: every write re-reads the file, MERGES this session's entry
and publishes the result with an atomic replace under a process-wide lock; a file that cannot be READ
puts the store in the DECLARED "unpinned" state, which the caller reports, and NO writer overwrites it.
Mechanism — `DOCUMENTATION.md` §16."""

import base64
import hashlib
import os
import socket
import threading

# paramiko compatibility: up to 5.x the module was called paramiko.host_keys,
# in paramiko 5.0+ it is named paramiko.hostkeys (the old name is gone).
try:
    import paramiko.hostkeys as _pk_hostkeys
except ImportError:  # paramiko <= 4.x
    import paramiko.host_keys as _pk_hostkeys

import paramiko  # the exception types the policy raises (SSHException)

try:
    from . import interactive_ask as _ask
except ImportError:  # flat launch from the project root
    import interactive_ask as _ask

try:  # the ONE atomic-write mechanism of the application (`DOCUMENTATION.md` §71)
    from ..storage import atomic as _atomic
except ImportError:  # flat launch from the project root
    from storage import atomic as _atomic

#: The budget of ONE host-key question, in seconds (the ask primitive's own bound is the default).
HOST_KEY_ASK_TIMEOUT_S = 300.0

#: The budget of the unauthenticated "what key does the server offer now" read.
PROBE_HOST_KEY_TIMEOUT_S = 10.0


def get_known_hosts_path() -> str:
    """Path to the application known_hosts (~/.sshmap/known_hosts)."""
    return os.path.join(os.path.expanduser("~"), ".sshmap", "known_hosts")


def entry_name_for(hostname: str, port) -> str:
    """The known_hosts entry name of one endpoint: `host`, or `[host]:port` off port 22.

    PURE, and the ONE place the spelling is decided: the policy writes through it, the manager dialog
    lists through it and the changed-key flow looks the entry up through it.
    """
    name = (hostname or "").strip()
    if not name:
        return "unknown"
    try:
        number = max(1, min(65535, int(port or 22)))
    except (TypeError, ValueError):
        number = 22
    return f"[{name}]:{number}" if number != 22 else name


def _log():
    """Lazy-imported logger — does not break the module if the logger is unavailable."""
    try:
        from .logger import get_logger as _gl
    except ImportError:
        try:
            from modules.logger import get_logger as _gl
        except Exception:
            return None
    try:
        return _gl("modules.host_key_policy")
    except Exception:  # noqa: BLE001
        return None


def _t(key, **kwargs) -> str:
    """A translated sentence (the policy reports to the USER, so its text is in the user's language)."""
    try:
        from i18n import t as _translate
    except Exception:  # noqa: BLE001 — no i18n: the key itself is the honest answer
        return key
    try:
        return _translate(key, **kwargs) if kwargs else _translate(key)
    except Exception:  # noqa: BLE001
        return key


class HostKeyRejected(paramiko.SSHException):
    """The user REFUSED a host key (a first connection, or a key that changed) — the connect is cancelled."""


def fingerprint(key) -> str:
    """Host key fingerprint in OpenSSH format (SHA256:<base64>).

    paramiko < 5 — `PKey.asbytes()` returned a base64 *string*; in paramiko >= 5 the same function
    returns the raw wire bytes of the key. The old code did b64decode on binary data: it either crashed
    ("<fingerprint unavailable>"), or (worse) produced a WRONG SHA256 that could not be verified
    out-of-band. Both formats are handled; the fallback is `get_base64()`.
    """
    blob = None
    for attr in ("asbytes", "get_base64"):
        fn = getattr(key, attr, None)
        if not callable(fn):
            continue
        try:
            raw = fn()
        except Exception:  # noqa: BLE001
            continue
        if isinstance(raw, bytes) and raw:
            blob = raw  # paramiko >= 5: wire format — hash it straight away
            break
        if isinstance(raw, str) and raw.strip():
            try:
                blob = base64.b64decode(raw)  # paramiko < 5 / get_base64()
                break
            except Exception:  # noqa: BLE001
                continue
    if not blob:
        return "<fingerprint unavailable>"
    digest = hashlib.sha256(blob).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii")


def read_server_host_key(host: str, port, timeout=PROBE_HOST_KEY_TIMEOUT_S):
    """The host key a server offers RIGHT NOW, WITHOUT authenticating: `(key, error)`.

    One TCP connection and one key exchange — the honest way to answer "what does the box present
    today?" from the manager dialog, because a key cannot be derived from a fingerprint. `error` is a
    short machine-free sentence and a failure answers `(None, text)`; never raises.
    """
    import paramiko as _paramiko
    try:
        number = max(1, min(65535, int(port or 22)))
    except (TypeError, ValueError):
        number = 22
    sock = None
    transport = None
    try:
        sock = socket.create_connection((host, number), timeout=timeout)
        transport = _paramiko.Transport(sock)
        transport.start_client(timeout=timeout)
        key = transport.get_remote_server_key()
        if key is None:
            return None, "the server offered no host key"
        return key, ""
    except Exception as e:  # noqa: BLE001 — every failure is data for the dialog
        return None, str(e)
    finally:
        for closer in (transport, sock):
            if closer is not None:
                try:
                    closer.close()
                except Exception:  # noqa: BLE001
                    pass


class KnownHostsStore:
    """The ONE owner of `~/.sshmap/known_hosts`.

    Read-modify-write, never write-a-snapshot: `pin()` re-reads the file under the lock, merges the
    entry and publishes it through `storage/atomic.py` (a unique prefixed provisional file + `fsync`
    + `os.replace`), so a long-lived session can no longer wipe a key pinned meanwhile and a crash
    can no longer leave a half file. A file that fails to LOAD is never overwritten (it may be
    repairable) and puts the store into the DECLARED "unpinned" state, which the caller reports.

    The cross-process answer is NOT restated here: it is the ONE declaration of `storage/atomic.py`.
    """

    def __init__(self, path=None):
        self._lock = threading.RLock()
        self._path_override = path
        self._loaded_once = False
        self.load_failed = False
        self.load_error = ""

    # ── the path ─────────────────────────────────────────────

    @property
    def path(self) -> str:
        """The store's path — the override of a test, otherwise the application's."""
        return self._path_override or get_known_hosts_path()

    # ── reading ──────────────────────────────────────────────

    def read(self):
        """A FRESH `HostKeys` read from the disk (an unreadable file answers an empty store).

        `load_failed` is set when the file EXISTS and cannot be parsed: the caller must not
        overwrite it, and the session is running unpinned — a fact the user is told.
        """
        store = _pk_hostkeys.HostKeys()
        path = self.path
        with self._lock:
            self._loaded_once = True
            try:
                store.load(path)
                self.load_failed = False
                self.load_error = ""
            except FileNotFoundError:
                # No file yet — normal first run, an empty store is fine.
                self.load_failed = False
                self.load_error = ""
            except Exception as e:  # noqa: BLE001 — a corrupt file must not break a connection
                self.load_failed = True
                self.load_error = str(e)
                log = _log()
                if log:
                    log.error(
                        "known_hosts file not loaded from %s: %s — the session runs UNPINNED "
                        "(the file is left as it is; repair or rename it to pin host keys again)",
                        path, e)
        return store

    def lookup(self, name: str):
        """The `{keytype: PKey}` map recorded for one entry name (None — unknown host)."""
        try:
            return self.read().lookup(name)
        except Exception:  # noqa: BLE001
            return None

    def entries(self) -> dict:
        """Every recorded entry as plain `{host: {keytype: key}}` (never the live store object)."""
        try:
            return dict(self.read())
        except Exception:  # noqa: BLE001
            return {}

    # ── writing ──────────────────────────────────────────────

    def pin(self, name: str, keytype: str, key) -> bool:
        """Record ONE host key and publish the merged file. False when nothing was written.

        The whole read-merge-write runs under the lock, so eight simultaneous connections keep
        eight entries instead of one — the merge is the point, an atomic write alone is not.
        An entry for `(name, keytype)` that already exists is REPLACED — that is the changed-key flow
        and the manager's "replace" both.
        """
        with self._lock:
            store = self.read()
            if self.load_failed:
                return self._refuse_overwrite()
            try:
                store.add(name, keytype, key)
                return self._write(store)
            except Exception as e:  # noqa: BLE001 — a pin failure never breaks a connection
                log = _log()
                if log:
                    log.error("Failed to save known_hosts (%s): %s", self.path, e)
                return False

    def remove(self, name: str, keytype=None) -> bool:
        """Drop ONE keytype of an entry, or the whole entry when `keytype` is None. False — nothing.

        The read-modify-write is the same as `pin()`'s and the refusal is the same: a file that failed
        to LOAD is never overwritten. `HostKeys` deletes a HOST line at a time, so the other keytypes
        of that host are re-added before the publish.
        """
        with self._lock:
            store = self.read()
            if self.load_failed:
                return self._refuse_overwrite()
            try:
                current = dict(store)
                if name not in current:
                    return False
                recorded = dict(current[name])
                if keytype is None:
                    doomed = set(recorded)
                elif keytype in recorded:
                    doomed = {keytype}
                else:
                    return False
                del store[name]
                for kind, key in recorded.items():
                    if kind in doomed:
                        continue
                    store.add(name, kind, key)
                return self._write(store)
            except Exception as e:  # noqa: BLE001 — a failed delete is a reported False
                log = _log()
                if log:
                    log.error("Failed to update known_hosts (%s): %s", self.path, e)
                return False

    def save(self) -> bool:
        """Re-read and publish the store unchanged (the shipped `save_store()` seam).

        The refusal `pin()` makes holds for EVERY writer: a file that failed to LOAD is never
        overwritten, because publishing an empty store over a file somebody could still repair is
        exactly how the keys are lost. False — nothing was written.
        """
        with self._lock:
            store = self.read()
            if self.load_failed:
                return self._refuse_overwrite()
            return self._write(store)

    def _refuse_overwrite(self) -> bool:
        """The ONE answer (False) and the ONE log line of "this file is not ours to rewrite"."""
        log = _log()
        if log:
            log.error(
                "Refusing to overwrite known_hosts: the file failed to load "
                "(possibly corrupted). Fix or remove the file manually.")
        return False

    def _write(self, store) -> bool:
        """Atomic publish through the ONE write mechanism of the application (`storage/atomic.py`).

        `store.save()` writes onto a UNIQUE provisional file, which is fsynced and replaced onto
        the published path; nothing ever truncates the file a reader may be opening.
        """
        path = self.path
        try:
            _atomic.publish_atomic(path, lambda temp: store.save(temp))
            return True
        except Exception as e:  # noqa: BLE001
            log = _log()
            if log:
                log.error("Failed to publish known_hosts (%s): %s", path, e)
            return False


#: The ONE process-wide store. `_store_override` is the test seam (`set_store()`), because a suite
#: must never touch the user's real `~/.sshmap/known_hosts`.
_store = KnownHostsStore()
_store_override = None


def get_store() -> KnownHostsStore:
    """The store this process writes through (a test's override, otherwise the one owner)."""
    return _store_override or _store


def set_store(store) -> None:
    """Install a store for the current process (tests). `set_store(None)` restores the owner."""
    global _store_override
    _store_override = store


def ask_new_host_key(hostname: str, port, key) -> bool:
    """Does the user TRUST this key? The ONE decision point of a first connection.

    `interactive_ask.ask()` answers `None` when no surface is installed; that is the DECLARED fallback
    and it is the shipped TOFU accept — a host key is trusted by the very policy that trusted it
    before this surface existed, and the log line names the fingerprint that was pinned.
    """
    keytype = key.get_name() if hasattr(key, "get_name") else ""
    shown = fingerprint(key)
    answer = _ask.ask(_ask.KIND_HOST_KEY, timeout=HOST_KEY_ASK_TIMEOUT_S,
                      host=hostname, port=port, keytype=keytype, fingerprint=shown)
    if answer is None:
        log = _log()
        if log:
            log.warning("No interactive surface for the host key of %s:%s — the declared fallback "
                        "accepts and pins %s", hostname, port, shown)
        return True
    return bool(answer)


def resolve_changed_key(exc, hostname: str, port) -> bool:
    """Offer a CHANGED key to the user and, on a yes, REPLACE the stored one. True — replaced.

    paramiko raises `BadHostKeyException` from inside `connect()` before any policy method runs, so
    this is the ONE recovery path of that failure: it names both fingerprints, and only a real write
    into the store answers True — a store that cannot be written leaves the connection refused rather
    than retrying against a key nobody recorded.
    """
    got = getattr(exc, "key", None)
    if got is None:
        got = getattr(exc, "got_key", None)   # the name some paramiko builds use
    expected = getattr(exc, "expected_key", None)
    if got is None or expected is None:
        return False
    keytype = got.get_name() if hasattr(got, "get_name") else ""
    new_shown = fingerprint(got)
    old_shown = fingerprint(expected)
    answer = _ask.ask(_ask.KIND_CHANGED_KEY, timeout=HOST_KEY_ASK_TIMEOUT_S,
                      host=hostname, port=port, keytype=keytype,
                      fingerprint=new_shown, expected=old_shown)
    if not answer:
        return False
    name = entry_name_for(hostname, port)
    pinned = bool(get_store().pin(name, keytype, got))
    log = _log()
    if log:
        if pinned:
            log.warning("Host key for %s replaced on the user's decision (%s → %s)",
                        name, old_shown, new_shown)
        else:
            log.error("The host key of %s was accepted but the store refused the write", name)
    return pinned


class SshKnownHostsPolicy:
    """Host key policy for `SSHClient.set_missing_host_key_policy()`.

    A host the store does not know asks the user for the fingerprint it is trusting; a key that
    differs from the stored one makes `connect()` raise `BadHostKeyException`, which
    `modules/ssh_connect.py` turns into the "replace the stored key" question.
    """

    def __init__(self, hostname: str = "", port: int = 22):
        self.hostname = (hostname or "").strip()
        try:
            self.port = max(1, min(65535, int(port or 22)))
        except (TypeError, ValueError):
            self.port = 22
        self.accepted_new_key = False  # True: a new host key was accepted in this session
        self.last_fingerprint = ""     # its fingerprint (for the user message)
        self.last_keytype = ""         # its algorithm (the prompt shows it)
        self.pinned = False            # True: the accepted key really reached the store

    # ── known_hosts store ────────────────────────────────────

    def _entry_name(self) -> str:
        """known_hosts entry name: host, or [host]:port for a non-standard port."""
        return entry_name_for(self.hostname, self.port)

    @property
    def store(self) -> KnownHostsStore:
        """The ONE store this policy reads and writes through."""
        return get_store()

    @property
    def load_failed(self) -> bool:
        """Is the store unreadable — i.e. is this session running UNPINNED?"""
        return bool(self.store.load_failed)

    def load_store(self):
        """The current store contents (a FRESH read — never a snapshot kept for the session's life)."""
        try:
            return self.store.read()
        except Exception:  # noqa: BLE001
            return _pk_hostkeys.HostKeys()

    def save_store(self) -> bool:
        """Re-read and publish the store (`save()`), False on a write error."""
        try:
            return self.store.save()
        except Exception as e:  # noqa: BLE001
            log = _log()
            if log:
                log.error(f"Failed to save known_hosts ({self.store.path}): {e}")
            return False

    def apply_to_client(self, client):
        """Attach the policy and the known keys to the SSHClient before connect()."""
        client.set_missing_host_key_policy(self)
        store = self.load_store()
        # paramiko 5.0: SSHClient.add_host_key() is gone — write to client.get_host_keys().
        try:
            client_keys = client.get_host_keys()
        except Exception:  # noqa: BLE001
            client_keys = None
        for host, keydict in dict(store).items():
            for keytype, key in list(keydict.items()):
                try:
                    if client_keys is not None:
                        client_keys.add(host, keytype, key)
                    else:  # paramiko <= 4.x fallback
                        client.add_host_key(host, keytype, key)
                except Exception as e:  # noqa: BLE001
                    log = _log()
                    if log:
                        log.warning(f"Skipped known_hosts entry {host} ({keytype}): {e}")

    # ── paramiko HostKeyPolicy interface ─────────────────────

    def missing_host_key(self, client, hostname, key):
        """A host the store does not know: ASK, then pin — and a refusal stops the connection.

        The key is accepted only when the user accepted it (or when no interactive surface exists, the
        declared TOFU fallback). `pinned` answers whether the entry really reached the store: with an
        unreadable file the key is accepted but NOTHING is remembered, and the caller says so.
        """
        self.last_fingerprint = fingerprint(key)
        self.last_keytype = key.get_name() if hasattr(key, "get_name") else ""
        if not ask_new_host_key(self.hostname, self.port, key):
            log = _log()
            if log:
                log.warning("Host key for %s:%s REJECTED by the user (%s)",
                            self.hostname, self.port, self.last_fingerprint)
            raise HostKeyRejected(
                _t("ssh.host_key_rejected", host=self.hostname, port=self.port,
                   fp=self.last_fingerprint))
        self.accepted_new_key = True
        log = _log()
        if log:
            log.warning(
                f"New SSH host key accepted for {self.hostname}:{self.port} "
                f"(fingerprint {self.last_fingerprint}). Saved to known_hosts — "
                f"first connection; verify the fingerprint out-of-band."
            )
        try:
            self.pinned = self.store.pin(self._entry_name(), self.last_keytype, key)
        except Exception as e:  # noqa: BLE001
            self.pinned = False
            if log:
                log.error(f"Failed to record new host key for {self.hostname}: {e}")
        if not self.pinned and log:
            log.error(
                "host key for %s:%s was accepted but NOT pinned — the host key store is "
                "unreadable (%s)", self.hostname, self.port, self.store.load_error or "unknown")

    def check(self, hostname, key):
        """A guard method.

        A key mismatch already raises BadHostKeyException inside connect(), before the policy is
        consulted; this method is a safety net for other versions/call paths.
        """
        entry = self.store.lookup(hostname) or self.store.lookup(f"[{hostname}]:{self.port}")
        if entry is None:
            return  # unknown host — missing_host_key will fire
        expected = entry.get(key.get_name())
        if expected is not None and expected.asbytes() != key.asbytes():
            raise paramiko.SSHException(
                f"Host key for {hostname} changed (possible MITM attack). "
                f"Expected {fingerprint(expected)}, got {fingerprint(key)}."
            )
