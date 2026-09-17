"""SSH host key policy (AUDIT v0.7.2, high #4 — MITM risk of AutoAddPolicy).

Instead of `paramiko.AutoAddPolicy()` (which silently accepts any host key), the
application uses its own known_hosts store in `~/.sshmap/known_hosts`:

* first connection to a server — the key is accepted, the SHA256 fingerprint is
  logged, and the entry is saved to the file (pinning for the future);
* subsequent connections — the received key is compared with the stored one. On
  a mismatch paramiko itself raises `BadHostKeyException` during connect()
  (possible "man in the middle" attack); the calling code shows the error.

The class implements the paramiko policy interface via duck typing
(`missing_host_key`, `check`) and imports paramiko lazily in the methods: the
module can be imported even where paramiko is not yet needed (headless tests).
The exception — the compatibility block below: it imports only the known_hosts
store submodule (without a full `import paramiko`) and is needed at module level
to pick the class name.
"""

import base64
import hashlib
import os

# paramiko compatibility: up to 5.x the module was called paramiko.host_keys,
# in paramiko 5.0+ it was renamed to paramiko.hostkeys (the old name was removed).
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
        self._store = None            # lazy paramiko.host_keys.HostKeys
        self._load_failed = False     # True if the file exists but failed to load
        self.accepted_new_key = False  # True: a new host key was accepted in this session
        self.last_fingerprint = ""     # its fingerprint (for the user message)

    # ── known_hosts store ────────────────────────────────────

    def _entry_name(self) -> str:
        """known_hosts entry name: host, or [host]:port for a non-standard port."""
        if not self.hostname:
            return "unknown"
        return f"[{self.hostname}]:{self.port}" if self.port != 22 else self.hostname

    def load_store(self):
        """Load known_hosts into memory (lazy paramiko import)."""
        if self._store is None:
            store = _pk_hostkeys.HostKeys()
            path = get_known_hosts_path()
            self._load_failed = False
            try:
                store.load(path)
            except FileNotFoundError:
                # No file yet — normal first run, an empty store is fine.
                pass
            except Exception as e:
                # AUDIT v0.9.5.5 (security #2): the file EXISTS but is corrupted —
                # work in memory with an empty store, but save_store() is forbidden,
                # otherwise the first TOFU addition would wipe all pinned keys.
                self._load_failed = True
                log = _log()
                if log:
                    log.warning(f"known_hosts file not loaded from {path}: {e}")
            self._store = store
        return self._store

    def save_store(self) -> bool:
        """Save known_hosts to disk. False on error (we do not break the connection)."""
        if self._load_failed:
            # Do not overwrite a corrupted file: let the user restore it manually.
            log = _log()
            if log:
                log.error(
                    "Refusing to overwrite known_hosts: the file failed to load "
                    "(possibly corrupted). Fix or remove the file manually."
                )
            return False
        try:
            path = get_known_hosts_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self.load_store().save(path)
            return True
        except Exception as e:
            log = _log()
            if log:
                log.error(f"Failed to save known_hosts ({get_known_hosts_path()}): {e}")
            return False

    def apply_to_client(self, client):
        """Attach the policy and the known keys to the SSHClient before connect()."""
        client.set_missing_host_key_policy(self)
        store = self.load_store()
        # paramiko 5.0: SSHClient.add_host_key() was removed — write to client.get_host_keys().
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
        """First connection to a host: accept the key, log the fingerprint, save it."""
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
            self.load_store().add(self._entry_name(), key.get_name(), key)
        except Exception as e:
            if log:
                log.error(f"Failed to record new host key for {self.hostname}: {e}")
        # save — best effort: the connection does not depend on the file write, but
        # without it the pinning on the next start would be lost.
        self.save_store()

    def check(self, hostname, key):
        """A guard method.

        In current paramiko a key mismatch already raises BadHostKeyException
        inside connect(), before the policy is consulted; this method is a
        safety net for other versions/call paths.
        """
        import paramiko
        store = self.load_store()
        entry = store.get(hostname) or store.get(f"[{hostname}]:{self.port}")
        if entry is None:
            return  # unknown host — missing_host_key will fire
        expected = entry.get(key.get_name())
        if expected is not None and expected.asbytes() != key.asbytes():
            raise paramiko.SSHException(
                f"Host key for {hostname} changed (possible MITM attack). "
                f"Expected {fingerprint(expected)}, got {fingerprint(key)}."
            )
