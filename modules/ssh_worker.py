import socket
from typing import Dict, Optional
from PySide6.QtCore import QThread, Signal

try:
    from .host_key_policy import SshKnownHostsPolicy
except ImportError:
    from modules.host_key_policy import SshKnownHostsPolicy


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


# ── Реестр активных worker'ов (патч v0.6.x) ─────────────────────
# server_id → запущенный SSHWorker. Заполняется при создании потока и
# очищается по сигналу finished(). Нужен, чтобы перед удалением ServerNode
# проверить корректное завершение его SSH-операции (AUDIT / план v0.6.x #2):
# иначе поток мог бы доставлять success/error в уже уничтоженный диалог или
# продолжать «писать» в данные удалённого узла.
_active_workers: Dict[str, "SSHWorker"] = {}


def get_active_worker(server_id: str) -> Optional["SSHWorker"]:
    """Активный (ещё не завершённый) SSHWorker для сервера или None."""
    if not server_id:
        return None
    worker = _active_workers.get(server_id)
    if worker is None or worker.isFinished():
        return None
    return worker


def wait_for_worker(server_id: str, timeout_ms: int = 5000) -> bool:
    """Дождаться завершения SSHWorker сервера.

    Возвращает True, если активного потока нет (или он завершился за
    timeout_ms). False — поток всё ещё работает; удалять узел не стоит.
    Все операции внутри worker имеют внутренние сетевые таймауты
    (socket 5 c / paramiko 15 c), поэтому wait() не висит бесконечно.
    """
    worker = get_active_worker(server_id)
    if worker is None:
        return True
    return bool(worker.wait(timeout_ms))


class SSHWorker(QThread):
    """Одноразовый поток для SSH-проверки/подключения без блокировки UI."""

    success = Signal(str)
    error = Signal(str)

    def __init__(self, host: str, user: str, port: int, server_id: str = "",
                 password: str = "", key_path: str = "",
                 test_only: bool = False, load_from_store: bool = True,
                 parent=None):
        super().__init__(parent)
        self.host = host
        self.user = user
        self.port = port
        self.server_id = server_id  # для загрузки из keyring
        self.password = password
        self.key_path = key_path
        self.test_only = test_only
        self.load_from_store = load_from_store

        # Регистрация в реестре активных worker'ов (патч v0.6.x): guard для
        # удаления узла. Авто-очистка — по finished() потока.
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
            # v0.9.3 fix: раньше здесь уходила хардкод-английская строка мимо i18n.
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

        # AUDIT v0.7.2 (высокая #4): вместо AutoAddPolicy — known_hosts-пиннинг:
        # новый ключ хоста принимается с логированием отпечатка, изменённый — отклоняется.
        client = paramiko.SSHClient()
        policy = SshKnownHostsPolicy(hostname=self.host, port=self.port)
        policy.apply_to_client(client)

        # Resolve password: explicit arg > credential manager > key-based fallback
        final_password = self.password or ""
        if not final_password and self.server_id and self.load_from_store:
            cm = get_credential_manager()
            cached_pw = cm.load_password(self.server_id)
            if cached_pw:
                final_password = cached_pw

        try:
            if self.key_path:
                client.connect(
                    self.host,
                    username=self.user,
                    port=self.port,
                    key_filename=self.key_path,
                    timeout=15,
                    look_for_keys=False,
                    allow_agent=True,
                )
            elif final_password:
                # v1.1.2RC1 (N5): паритет с ssh_terminal.py — при попытке пароля
                # НЕ опрашиваем локальные ключи/ssh-agent (дефолты paramiko True/True
                # добавляли задержку и могли «подцепить» чужой ключ из agent до
                # попытки пароля).
                client.connect(
                    self.host,
                    username=self.user,
                    password=final_password,
                    port=self.port,
                    timeout=15,
                    look_for_keys=False,
                    allow_agent=False,
                )
            else:
                # Pure key-based / agent fallback
                client.connect(
                    self.host,
                    username=self.user,
                    port=self.port,
                    timeout=15,
                    look_for_keys=True,
                    allow_agent=True,
                )

            msg = t("ssh.connected_ok", host=self.host)
            # AUDIT v0.7.2 (высокая #4): первое подключение — предупредить о принятом ключе
            if policy.accepted_new_key and policy.last_fingerprint:
                note = t("ssh.host_key_new", host=self.host, fp=policy.last_fingerprint)
                msg += "\n" + (note if not note.startswith("[") else f"New host key accepted ({policy.last_fingerprint})")
            self.success.emit(msg if not msg.startswith("[") else f"✓ Connected to {self.host}")
        except paramiko.BadHostKeyException as e:
            # AUDIT v0.7.2 (высокая #4): сохранённый ключ хоста изменился — вероятен MITM
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
        finally:
            client.close()
