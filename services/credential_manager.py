"""Credential Manager — secure storage for SSH passwords using keyring (AGENTS.md §4.4).

A stored password belongs to the ENDPOINT it was saved for, not to the node id alone: the keyring keeps
the secret under `sshmap:{id}` and its scope (`user@host:port`) under a sibling entry, and
`load_password()` refuses a secret whose scope is not the endpoint asking for it. A bare entry written
before the scope existed is ADOPTED once, for the endpoint the node names at that moment. The
`profile:{id}` family is deliberately host-agnostic — a reusable credential the user attaches to a node.
Without a keyring the app still works and nothing is persisted.

    cm = get_credential_manager()
    cm.load_password(server_id, scope=node_scope(data))
"""

from typing import Optional
import platform as _platform_mod

#: The ONE marker of "this entry belongs to an endpoint" in the node record's own spelling.
SCOPE_SUFFIX = "#scope"


def endpoint_scope(user, host, port) -> str:
    """The ONE spelling of a credential's endpoint: `user@host:port` (PURE).

    Every read and every write compares THIS string, so the rule lives in one place instead of at the
    call sites. A missing port is 22 and a missing user or host renders as an empty piece — an
    endpoint is never invented.
    """
    try:
        number = max(1, min(65535, int(port or 22)))
    except (TypeError, ValueError):
        number = 22
    return f"{str(user or '').strip()}@{str(host or '').strip()}:{number}"


def node_scope(data) -> str:
    """`endpoint_scope()` read off a node-like object (`user`/`host`/`ssh_port` or `port`).

    Never raises: a record without the fields answers an empty scope, which every caller reads as
    "no endpoint known" — the shipped unscoped read.
    """
    if data is None:
        return ""
    try:
        user = getattr(data, "user", "")
        host = getattr(data, "host", "")
        port = getattr(data, "ssh_port", None)
        if port in (None, "", 0):
            port = getattr(data, "port", None)
        return endpoint_scope(user, host, port)
    except Exception:  # noqa: BLE001 — a broken record is not a credential scope
        return ""


def _log():
    """The module logger, or None — the manager must work without the logging stack."""
    try:
        from modules.logger import get_logger
        return get_logger("services.credential_manager")
    except Exception:  # noqa: BLE001
        return None


class CredentialManager:
    """Abstraction around keyring for SSH credentials."""

    def __init__(self):
        self._keyring_backend = None
        self._backend_available = False
        self._try_init()

    # AUDIT v0.9.5.5 (security #1): secure Windows backends (allowlist).
    # keyring 24.x: keyrings.win.keyring.WindowsCredKeyring
    # keyring 25.x: keyring.backends.Windows.WinVaultKeyring — the same wincred, new package layout.
    _WINDOWS_SECURE_CLASSES = ("windowscredkeyring", "winvaultkeyring")

    def _try_init(self):
        """Try to initialize a working keyring backend. Falls back gracefully.

        On Windows — a strict allowlist, Windows Credential Manager (wincred) only: the
        WindowsCredKeyring class (keyring 24.x, keyrings.win.* module) or WinVaultKeyring (keyring
        25.x, keyring.backends.Windows module). Without pywin32 keyring may silently pick
        keyrings.alt.file — a plaintext file; such backends are rejected, is_available=False. On other
        OSes the known-insecure (keyrings.alt.*) and the non-functional (keyring.backends.fail)
        backends are rejected. Read/write go ONLY through the accepted backend (see save/load/delete).
        """
        try:
            import keyring
            import keyring.errors  # noqa: F401

            kr = keyring.get_keyring()
            if kr is None or not hasattr(kr, "name"):
                self._backend_available = False
                return
            cls = type(kr)
            class_name = cls.__name__.lower()
            backend_name = getattr(kr, "name", "") or ""
            backend_module = (cls.__module__ or "").lower()
            if _platform_mod.system() == "Windows":
                ok = (
                    class_name in self._WINDOWS_SECURE_CLASSES
                    or backend_module.startswith("keyrings.win")
                    or backend_module.startswith("keyring.backends.windows")
                )
            else:
                ok = (
                    not backend_module.startswith("keyrings.alt")
                    and not backend_module.startswith("keyring.backends.fail")
                    and "plaintext" not in class_name
                    and "plaintext" not in backend_module
                )
            if ok:
                self._keyring_backend = kr
                self._backend_available = True
            else:
                # AUDIT v1.2.10 (manual #2): get_logger() with no argument raised TypeError
                # (name — a required positional argument, modules/logger.py), which was swallowed
                # by the surrounding except — the warning never made it to the log.
                log = _log()
                if log:
                    log.warning(
                        f"Rejected keyring backend '{backend_name}' "
                        f"({cls.__module__}.{cls.__name__}): "
                        "plaintext/insecure fallback is not allowed for credentials."
                    )
                self._backend_available = False
        except Exception:
            # No keyring backend available (e.g., headless system)
            self._backend_available = False

    @property
    def is_available(self) -> bool:
        """Return True if a working credential store is available."""
        return self._backend_available

    def _get_service_name(self, server_id: str) -> str:
        """Generate a unique keyring service name for this server."""
        return f"sshmap:{server_id}"

    def _get_scope_username(self, server_id: str) -> str:
        """The username of the SCOPE entry beside the secret (`scope` is never a secret itself)."""
        return f"{server_id}{SCOPE_SUFFIX}"

    def _read(self, service: str, username: str) -> Optional[str]:
        """One backend read; every backend error is None (the shipped degradation)."""
        import keyring.errors
        try:
            return self._keyring_backend.get_password(service, username)
        except keyring.errors.NoKeyringError:
            return None
        except Exception as e:  # noqa: BLE001
            log = _log()
            if log:
                log.warning(f"Failed to load credential entry {username!r}: {e}")
            return None

    def _write(self, service: str, username: str, value: str) -> bool:
        """One backend write; False when the store refuses it (never a plaintext fallback)."""
        import keyring.errors
        try:
            self._keyring_backend.set_password(service, username, value)
            return True
        except keyring.errors.NoKeyringError:
            return False
        except Exception as e:  # noqa: BLE001
            log = _log()
            if log:
                log.warning(f"Failed to save credential entry {username!r}: {e}")
            return False

    def _drop(self, service: str, username: str) -> bool:
        """One backend delete; a missing entry is a success, a refusal is None."""
        import keyring.errors
        try:
            self._keyring_backend.delete_password(service, username)
            return True
        except keyring.errors.NoKeyringError:
            return True
        except Exception as e:  # noqa: BLE001
            _pde = getattr(keyring.errors, "PasswordDeleteError", None)
            if _pde is not None and isinstance(e, _pde):
                return True
            log = _log()
            if log:
                log.warning(f"Failed to delete credential entry {username!r}: {e}")
            return False

    # ── the endpoint binding (N47) ───────────────────────────

    def stored_scope(self, server_id: str) -> str:
        """The endpoint this credential was saved FOR, or "" (legacy entry / nothing stored).

        The question the connect dialog asks to explain a password the store deliberately withholds:
        a non-empty answer that differs from the endpoint in front of the user is the honest reason.
        """
        if not self._backend_available or self._keyring_backend is None:
            return ""
        value = self._read(self._get_service_name(server_id), self._get_scope_username(server_id))
        return (value or "").strip()

    def save_password(self, server_id: str, password: str, scope: str = "") -> bool:
        """Save a password for a server to the system credential store.

        Args:
            server_id: The 8-char UUID of the ServerData instance
            password: The SSH password to store
            scope: `endpoint_scope(user, host, port)` of the endpoint it is saved FOR. Without one the
                entry is stored UNSCOPED (and any previous scope is dropped), which the next scoped
                read treats as a legacy entry and adopts.

        Returns:
            True if saved successfully, False if keyring unavailable

        The write goes ONLY through the accepted verified backend (self._keyring_backend), not through
        the global keyring API — otherwise a rejected plaintext backend could still receive the
        password when called from code that does not check is_available.
        """
        if not self._backend_available or self._keyring_backend is None:
            return False
        service = self._get_service_name(server_id)
        if not self._write(service, server_id, password):
            return False
        wanted = (scope or "").strip()
        if wanted:
            self._write(service, self._get_scope_username(server_id), wanted)
        else:
            self._drop(service, self._get_scope_username(server_id))
        return True

    def load_password(self, server_id: str, scope: Optional[str] = None) -> Optional[str]:
        """Load a stored password for the endpoint that is asking for it.

        Args:
            server_id: The 8-char UUID of the ServerData instance
            scope: `endpoint_scope(user, host, port)` of the endpoint in front of us. `None` (or an
                empty string) is the caller that HAS no endpoint — the shipped unscoped read.

        Returns:
            The stored password, or None when it is not found, unavailable, or SAVED FOR ANOTHER
            ENDPOINT. A credential saved before the scope existed is adopted once for `scope` and
            reported in the log; a credential whose scope differs is NOT injected and the refusal is
            logged — the node's field stays empty and the connect dialog asks.
        """
        if not self._backend_available or self._keyring_backend is None:
            return None
        service = self._get_service_name(server_id)
        secret = self._read(service, server_id)
        if secret is None:
            return None
        wanted = (scope or "").strip()
        if not wanted:
            return secret
        saved = self.stored_scope(server_id)
        if saved == wanted:
            return secret
        log = _log()
        if not saved:
            # The one-time adoption: every entry written before the scope existed is bare, and asking
            # the user again for every stored password on the first run of this release is worse.
            self._write(service, self._get_scope_username(server_id), wanted)
            if log:
                log.info("The stored credential of %s had no endpoint scope — adopted for %s",
                         server_id, wanted)
            return secret
        if log:
            log.warning("The stored credential of %s belongs to %s and is NOT used for %s",
                        server_id, saved, wanted)
        return None

    def delete_password(self, server_id: str) -> bool:
        """Delete a stored password (and its scope) from the system credential store.

        Returns:
            True if deleted successfully or not found, False on error
        """
        if not self._backend_available or self._keyring_backend is None:
            return True  # Nothing to delete — no store available
        service = self._get_service_name(server_id)
        removed = self._drop(service, server_id)
        self._drop(service, self._get_scope_username(server_id))
        return removed

    # The dead legacy API is gone: _get_username(), save_credentials()/load_credentials() were never
    # called anywhere, and their username key format disagreed with _get_username("sshmap:{id}.user").


# Module-level singleton (initialized lazily)
_cm_instance = None


def get_credential_manager() -> CredentialManager:
    """Get or create the singleton CredentialManager instance."""
    global _cm_instance
    if _cm_instance is None:
        _cm_instance = CredentialManager()
    return _cm_instance
