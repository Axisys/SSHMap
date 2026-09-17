"""Credential Manager — secure storage for SSH passwords using keyring.

Fallback: if keyring is not available (NoKeyringError), returns empty string
so the app still works without a system credential store.

Usage in any module:
    from services.credential_manager import CredentialManager
    cm = CredentialManager()  # or get_credential_manager()
    password = cm.load_password(server_id)
    cm.save_password(server_id, new_password)
    cm.delete_password(server_id)
"""

from typing import Optional
import platform as _platform_mod


class CredentialManager:
    """Abstraction around keyring for SSH credentials."""

    def __init__(self):
        self._keyring_backend = None
        self._backend_available = False
        self._try_init()

    # AUDIT v0.9.5.5 (security #1): secure Windows backends (allowlist).
    # keyring 24.x: keyrings.win.keyring.WindowsCredKeyring
    # keyring 25.x: keyring.backends.Windows.WinVaultKeyring — the same wincred,
    # new package layout (checking only the old "keyrings.win" prefix
    # discarded even this store → is_available=False on machines with pywin32).
    _WINDOWS_SECURE_CLASSES = ("windowscredkeyring", "winvaultkeyring")

    def _try_init(self):
        """Try to initialize a working keyring backend. Falls back gracefully.

        AUDIT v0.9.5.5 (security #1): on Windows — a strict allowlist,
        Windows Credential Manager (wincred) only: the WindowsCredKeyring class
        (keyring 24.x, keyrings.win.* module) or WinVaultKeyring (keyring 25.x,
        keyring.backends.Windows module). Without pywin32 keyring may silently pick
        keyrings.alt.file — a plaintext file; such backends are rejected,
        is_available=False. On other OSes — we reject the known-insecure
        (keyrings.alt.*) and the non-functional (keyring.backends.fail) backends.
        Read/write go ONLY through the accepted backend (see save/load/delete) —
        bypassing the global keyring API is forbidden.
        """
        try:
            # v1.2.10rc2 (AUDIT auto #7): explicit import keyring — previously the name was bound
            # as a side effect of the `import keyring.errors` below; it worked, but was
            # fragile in terms of readability. keyring.errors is needed separately: its
            # exceptions are caught in save/load/delete.
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
                # Strict allowlist: wincred (Windows Credential Manager) only
                ok = (
                    class_name in self._WINDOWS_SECURE_CLASSES
                    or backend_module.startswith("keyrings.win")
                    or backend_module.startswith("keyring.backends.windows")
                )
            else:
                # Blacklist: plaintext file backends and the fail backend
                # (whose get/set/delete raise NoKeyringError — nowhere to store)
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
                # v1.2.10 (AUDIT manual #2): get_logger() with no argument raised TypeError
                # (name — a required positional argument, modules/logger.py), which was swallowed
                # by the surrounding except — the warning "Rejected keyring backend" documented
                # in DOCUMENTATION.md never made it to the log.
                log = None
                try:
                    from modules.logger import get_logger
                    log = get_logger("services.credential_manager")
                except Exception:
                    pass
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

    def save_password(self, server_id: str, password: str) -> bool:
        """Save a password for a server to the system credential store.

        Args:
            server_id: The 8-char UUID of the ServerData instance
            password: The SSH password to store

        Returns:
            True if saved successfully, False if keyring unavailable

        AUDIT v0.9.5.5 (security #1): the write goes ONLY through the accepted
        verified backend (self._keyring_backend), not through the global
        keyring API — otherwise a rejected plaintext backend could still
        receive the password when called from code that does not check is_available.
        """
        if not self._backend_available or self._keyring_backend is None:
            # Backend rejected (or unavailable): refuse the write — the password
            # must not end up in a plaintext file. The caller must react (a UI
            # warning), see is_available.
            return False
        try:
            import keyring.errors
            service = self._get_service_name(server_id)
            self._keyring_backend.set_password(service, server_id, password)
            return True
        except keyring.errors.NoKeyringError:
            # Fallback: backend was accepted but store rejected the write
            return False
        except Exception as e:
            # Other errors (e.g., backend busy) — log but don't crash
            try:
                from modules.logger import get_logger
                log = get_logger("services.credential_manager")
                log.warning(f"Failed to save password for {server_id}: {e}")
            except Exception:
                pass
            return False

    def load_password(self, server_id: str) -> Optional[str]:
        """Load a stored password from the system credential store.

        Args:
            server_id: The 8-char UUID of the ServerData instance

        Returns:
            Stored password string, or None if not found/unavailable

        AUDIT v0.9.5.5 (security #1): read only through the accepted
        verified backend, without the global keyring API.
        """
        if not self._backend_available or self._keyring_backend is None:
            return None
        try:
            import keyring.errors
            service = self._get_service_name(server_id)
            pw = self._keyring_backend.get_password(service, server_id)
            return pw  # None means not stored
        except keyring.errors.NoKeyringError:
            return None
        except Exception as e:
            try:
                from modules.logger import get_logger
                log = get_logger("services.credential_manager")
                log.warning(f"Failed to load password for {server_id}: {e}")
            except Exception:
                pass
            return None

    def delete_password(self, server_id: str) -> bool:
        """Delete a stored password from the system credential store.

        Args:
            server_id: The 8-char UUID of the ServerData instance

        Returns:
            True if deleted successfully or not found, False on error

        AUDIT v0.9.5.5 (security #1): deletion only through the accepted
        verified backend. If the backend was rejected — True: nothing was stored
        in the rejected backend, so there is nothing to delete (matches the v094b test).
        """
        if not self._backend_available or self._keyring_backend is None:
            return True  # Nothing to delete — no store available
        try:
            import keyring.errors
            service = self._get_service_name(server_id)
            self._keyring_backend.delete_password(service, server_id)
            return True
        except keyring.errors.NoKeyringError:
            return True  # Nothing to delete — no store available
        except Exception as e:
            # v1.2.10rc2 (AUDIT manual #6): an explicit PasswordDeleteError check instead of
            # the misleading `except getattr(keyring.errors, "PasswordDeleteError", ())` —
            # when the attribute is missing, except () never fired and the exception
            # silently fell through to the generic handler. Now the same degradation (the
            # generic handler), but without the misdirection: the class via getattr(..., None)
            # + isinstance.
            _pde = getattr(keyring.errors, "PasswordDeleteError", None)  # keyring 25.x
            if _pde is not None and isinstance(e, _pde):
                return True  # Nothing to delete — entry was already absent
            try:
                from modules.logger import get_logger
                log = get_logger("services.credential_manager")
                log.warning(f"Failed to delete password for {server_id}: {e}")
            except Exception:
                pass
            return False

    # AUDIT v0.7.2 (medium #12): the dead legacy API removed — _get_username(),
    # save_credentials()/load_credentials() were never called anywhere, and their
    # username key format ("{server_id}.user") disagreed with _get_username("sshmap:{id}.user").

# Module-level singleton (initialized lazily)
_cm_instance = None


def get_credential_manager() -> CredentialManager:
    """Get or create the singleton CredentialManager instance."""
    global _cm_instance
    if _cm_instance is None:
        _cm_instance = CredentialManager()
    return _cm_instance
