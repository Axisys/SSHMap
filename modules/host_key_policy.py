"""SSH host key policy — the answer to the MITM risk of `paramiko.AutoAddPolicy()` (AGENTS.md §4.4).

Instead of silently accepting any host key, the application keeps its OWN known_hosts store in
`~/.sshmap/known_hosts`: on the FIRST connection a key is accepted, its SHA256 fingerprint is logged
and the entry is pinned, and on every LATER connection the received key is compared with the stored
one — a mismatch makes paramiko itself raise `BadHostKeyException` during `connect()`.

The store has ONE owner, `KnownHostsStore`: every write re-reads the file, MERGES this session's
entry and publishes the result with an atomic replace under a process-wide lock; a file that cannot
be READ puts the store in the DECLARED "unpinned" state, which the caller reports.

`SshKnownHostsPolicy` duck-types paramiko's policy interface; mechanism — `DOCUMENTATION.md` §16."""

import base64
import hashlib
import os
import threading

# paramiko compatibility: up to 5.x the module was called paramiko.host_keys,
# in paramiko 5.0+ it is named paramiko.hostkeys (the old name is gone).
# Note: this is NOT a lazy `import paramiko` — it only pulls the hostkeys submodule.
try:
    import paramiko.hostkeys as _pk_hostkeys
except ImportError:  # paramiko <= 4.x
    import paramiko.host_keys as _pk_hostkeys


def get_known_hosts_path() -> str:
    """Path to the application known_hosts (~/.sshmap/known_hosts)."""
    return os.path.join(os.path.expanduser("~"), ".sshmap", "known_hosts")


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
    except Exception:
        return None


def fingerprint(key) -> str:
    """Host key fingerprint in OpenSSH format (SHA256:<base64>).

    v0.8.1: paramiko < 5 — `PKey.asbytes()` returned a base64 *string*; in paramiko >= 5
    the same function returns the raw wire bytes of the key. The old code did b64decode
    on binary data: it either crashed ("<fingerprint unavailable>"), or (worse) produced
    a WRONG SHA256 that could not be verified out-of-band. Now both formats are
    handled; the fallback is `get_base64()` (a base64 string in both paramiko versions).
    """
    blob = None
    for attr in ("asbytes", "get_base64"):
        fn = getattr(key, attr, None)
        if not callable(fn):
            continue
        try:
            raw = fn()
        except Exception:
            continue
        if isinstance(raw, bytes) and raw:
            blob = raw  # paramiko >= 5: wire format — hash it straight away
            break
        if isinstance(raw, str) and raw.strip():
            try:
                blob = base64.b64decode(raw)  # paramiko < 5 / get_base64()
                break
            except Exception:
                continue
    if not blob:
        return "<fingerprint unavailable>"
    digest = hashlib.sha256(blob).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii")


class KnownHostsStore:
    """The ONE owner of `~/.sshmap/known_hosts` (v1.7.5.1, N48).

    Read-modify-write, never write-a-snapshot: `pin()` re-reads the file under the lock, merges the
    entry and publishes it with `<path>.tmp` + `fsync` + `os.replace`, so a long-lived session can no
    longer wipe a key pinned meanwhile and a crash can no longer leave a half file. A file that fails
    to LOAD is never overwritten (it may be repairable) and puts the store into the DECLARED
    "unpinned" state, which the caller reports to the user.

    Cross-process writers are deliberately OUT of scope and declared: the lock is a `threading.Lock`
    (this application instance), and the atomic replace is what keeps a second instance from seeing a
    truncated file.
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
        """Atomic publish: the SAME directory, `<path>.tmp`, fsync, then `os.replace`."""
        path = self.path
        temp = path + ".tmp"
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        try:
            # `HostKeys.save()` truncates and writes line by line — onto the TEMP name, which is
            # exactly the shape that is safe for; nothing ever truncates the published file.
            store.save(temp)
            handle = os.open(temp, os.O_RDWR)
            try:
                os.fsync(handle)   # the bytes on the disk BEFORE the replace
            finally:
                os.close(handle)
            os.replace(temp, path)
            return True
        except Exception as e:  # noqa: BLE001
            log = _log()
            if log:
                log.error("Failed to publish known_hosts (%s): %s", path, e)
            try:
                os.remove(temp)
            except OSError:
                pass
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


class SshKnownHostsPolicy:
    """Host key policy for `SSHClient.set_missing_host_key_policy()`.

    Trusted keys are stored in the known_hosts file (paramiko.HostKeys format).
    New host: the key is accepted and pinned. A changed stored key:
    connect() is aborted with BadHostKeyException before check() is called.
    """

    def __init__(self, hostname: str = "", port: int = 22):
        self.hostname = (hostname or "").strip()
        try:
            self.port = max(1, min(65535, int(port or 22)))
        except (TypeError, ValueError):
            self.port = 22
        self.accepted_new_key = False  # True: a new host key was accepted in this session
        self.last_fingerprint = ""     # its fingerprint (for the user message)
        self.pinned = False            # True: the accepted key really reached the store

    # ── known_hosts store ────────────────────────────────────

    def _entry_name(self) -> str:
        """known_hosts entry name: host, or [host]:port for a non-standard port."""
        if not self.hostname:
            return "unknown"
        return f"[{self.hostname}]:{self.port}" if self.port != 22 else self.hostname

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
        """Re-read and publish the store (`save()`), False on a write error.

        The store no longer caches a snapshot for the policy's life, so a save can never publish a
        stale view — the shipped callers keep working and now mean "publish what is on the disk".
        """
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
        except Exception:
            client_keys = None
        for host, keydict in dict(store).items():
            for keytype, key in list(keydict.items()):
                try:
                    if client_keys is not None:
                        client_keys.add(host, keytype, key)
                    else:  # paramiko <= 4.x fallback
                        client.add_host_key(host, keytype, key)
                except Exception as e:
                    log = _log()
                    if log:
                        log.warning(f"Skipped known_hosts entry {host} ({keytype}): {e}")

    # ── paramiko HostKeyPolicy interface ─────────────────────

    def missing_host_key(self, client, hostname, key):
        """First connection to a host: accept the key, log the fingerprint, pin it.

        `pinned` answers whether the entry really reached the store: with an unreadable file the
        key is accepted (TOFU) but NOTHING is remembered, and the caller must report that state
        instead of the ordinary "new host key accepted" note.
        """
        self.last_fingerprint = fingerprint(key)
        self.accepted_new_key = True
        log = _log()
        if log:
            log.warning(
                f"New SSH host key accepted for {self.hostname}:{self.port} "
                f"(fingerprint {self.last_fingerprint}). Saved to known_hosts — "
                f"first connection; verify the fingerprint out-of-band."
            )
        try:
            self.pinned = self.store.pin(self._entry_name(), key.get_name(), key)
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

        In current paramiko a key mismatch already raises BadHostKeyException
        inside connect(), before the policy is consulted; this method is a
        safety net for other versions/call paths.
        """
        import paramiko
        entry = self.store.lookup(hostname) or self.store.lookup(f"[{hostname}]:{self.port}")
        if entry is None:
            return  # unknown host — missing_host_key will fire
        expected = entry.get(key.get_name())
        if expected is not None and expected.asbytes() != key.asbytes():
            raise paramiko.SSHException(
                f"Host key for {hostname} changed (possible MITM attack). "
                f"Expected {fingerprint(expected)}, got {fingerprint(key)}."
            )
