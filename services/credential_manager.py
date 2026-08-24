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


class CredentialManager:
    """Abstraction around keyring for SSH credentials."""

    def __init__(self):
        self._keyring_backend = None
        self._backend_available = False
        self._try_init()

    def _try_init(self):
        """Try to initialize a working keyring backend. Falls back gracefully."""
        try:
            import keyring.errors

            # Get the current keyring backend
            kr = keyring.get_keyring()
            if kr is not None and hasattr(kr, "name"):
                self._keyring_backend = kr
                self._backend_available = True
            else:
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
        """
        try:
            import keyring.errors
            service = self._get_service_name(server_id)
            keyring.set_password(service, server_id, password)
            return True
        except keyring.errors.NoKeyringError:
            # Fallback: no credential store available
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
        """
        try:
            import keyring.errors
            service = self._get_service_name(server_id)
            pw = keyring.get_password(service, server_id)
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
        """
        try:
            import keyring.errors
            service = self._get_service_name(server_id)
            keyring.delete_password(service, server_id)
            return True
        except keyring.errors.NoKeyringError:
            return True  # Nothing to delete — no store available
        except Exception as e:
            try:
                from modules.logger import get_logger
                log = get_logger("services.credential_manager")
                log.warning(f"Failed to delete password for {server_id}: {e}")
            except Exception:
                pass
            return False

    # AUDIT v0.7.2 (средняя #12): мёртвый legacy-API удалён — _get_username(),
    # save_credentials()/load_credentials() не вызывались нигде, а их формат имени
    # ключа username ("{server_id}.user") расходился с _get_username("sshmap:{id}.user").

# Module-level singleton (initialized lazily)
_cm_instance = None


def get_credential_manager() -> CredentialManager:
    """Get or create the singleton CredentialManager instance."""
    global _cm_instance
    if _cm_instance is None:
        _cm_instance = CredentialManager()
    return _cm_instance
