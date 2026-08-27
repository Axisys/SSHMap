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

    # AUDIT v0.9.5.5 (безопасность #1): безопасные бэкенды Windows (allowlist).
    # keyring 24.x: keyrings.win.keyring.WindowsCredKeyring
    # keyring 25.x: keyring.backends.Windows.WinVaultKeyring — тот же wincred,
    # новый layout пакета (проверка только по старому префиксу «keyrings.win»
    # отбрасывала даже это хранилище → is_available=False на машинах с pywin32).
    _WINDOWS_SECURE_CLASSES = ("windowscredkeyring", "winvaultkeyring")

    def _try_init(self):
        """Try to initialize a working keyring backend. Falls back gracefully.

        AUDIT v0.9.5.5 (безопасность #1): на Windows — строгий allowlist,
        только Windows Credential Manager (wincred): класс WindowsCredKeyring
        (keyring 24.x, модуль keyrings.win.*) или WinVaultKeyring (keyring 25.x,
        модуль keyring.backends.Windows). Без pywin32 keyring может молча выбрать
        keyrings.alt.file — plaintext-файл; такие бэкенды отвергаются,
        is_available=False. На других ОС — отвергаем заведомо небезопасные
        (keyrings.alt.*) и неработающие (keyring.backends.fail) бэкенды.
        Запись/чтение идут ТОЛЬКО через принятый бэкенд (см. save/load/delete) —
        глобальный keyring API обходить запрещено.
        """
        try:
            import keyring.errors  # noqa: F401 — исключения перехватываются в save/load/delete

            kr = keyring.get_keyring()
            if kr is None or not hasattr(kr, "name"):
                self._backend_available = False
                return
            cls = type(kr)
            class_name = cls.__name__.lower()
            backend_name = getattr(kr, "name", "") or ""
            backend_module = (cls.__module__ or "").lower()
            if _platform_mod.system() == "Windows":
                # Строгий allowlist: только wincred (Windows Credential Manager)
                ok = (
                    class_name in self._WINDOWS_SECURE_CLASSES
                    or backend_module.startswith("keyrings.win")
                    or backend_module.startswith("keyring.backends.windows")
                )
            else:
                # Чёрный список: plaintext-файловые бэкенды и fail-бэкенд
                # (у которого get/set/delete бросают NoKeyringError — хранить негде)
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
                log = None
                try:
                    from modules.logger import get_logger
                    log = get_logger()
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

        AUDIT v0.9.5.5 (безопасность #1): запись идёт ТОЛЬКО через принятый
        проверенный бэкенд (self._keyring_backend), а не через глобальный
        keyring API — иначе отклонённый plaintext-бэкенд всё равно мог бы
        получить пароль при вызове из кода, не проверяющего is_available.
        """
        if not self._backend_available or self._keyring_backend is None:
            # Бэкенд отклонён (или недоступен): отказ от записи — пароль не
            # уходит в plaintext-файл. Вызывающий обязан отреагировать (UI-
            # предупреждение), см. is_available.
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

        AUDIT v0.9.5.5 (безопасность #1): чтение только через принятый
        проверенный бэкенд, без глобального keyring API.
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

        AUDIT v0.9.5.5 (безопасность #1): удаление только через принятый
        проверенный бэкенд. Если бэкенд отклонён — True: ничего не хранилось
        в отклонённом бэкенде, удалять нечего (соответствует v094b-тесту).
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
        except getattr(keyring.errors, "PasswordDeleteError", ()):  # keyring 25.x: запись отсутствовала
            return True  # Nothing to delete — entry was already absent
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
