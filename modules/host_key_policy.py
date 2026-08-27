"""SSH host key policy (AUDIT v0.7.2, высокая #4 — MITM-риск AutoAddPolicy).

Вместо `paramiko.AutoAddPolicy()` (молча принимает любой ключ хоста) приложение
использует собственное known_hosts-хранилище в `~/.sshmap/known_hosts`:

* первое подключение к серверу — ключ принимается, SHA256-отпечаток логируется
  и запись сохраняется в файл (pinning на будущее);
* повторные подключения — полученный ключ сравнивается с сохранённым. При
  несоответствии paramiko сам поднимает `BadHostKeyException` во время connect()
  (возможна атака «человек посередине»); вызывающий код показывает ошибку.

Класс реализует интерфейс политики paramiko через duck typing (`missing_host_key`,
`check`) и импортирует paramiko лениво в методах: модуль можно импортировать даже
там, где paramiko ещё не нужен (headless-тесты). Исключение — блок совместимости
ниже: он импортирует только субмодуль known_hosts-хранилища (без полного
`import paramiko`) и нужен на уровне модуля для выбора имени класса.
"""

import base64
import hashlib
import os

# Совместимость paramiko: до 5.x включительно модуль назывался paramiko.host_keys,
# в paramiko 5.0+ переименован в paramiko.hostkeys (старое имя удалено).
# Примечание: это НЕ ленивый `import paramiko` — тянет лишь субмодуль hostkeys.
try:
    import paramiko.hostkeys as _pk_hostkeys
except ImportError:  # paramiko <= 4.x
    import paramiko.host_keys as _pk_hostkeys


def get_known_hosts_path() -> str:
    """Путь к known_hosts приложения (~/.sshmap/known_hosts)."""
    return os.path.join(os.path.expanduser("~"), ".sshmap", "known_hosts")


def _log():
    """Lazy-imported logger — не роняет модуль, если логгер недоступен."""
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
    """Отпечаток ключа хоста в OpenSSH-формате (SHA256:<base64>).

    v0.8.1: paramiko < 5 — `PKey.asbytes()` возвращал base64-*строку*; в paramiko >= 5
    та же функция возвращает сырые wire-байты ключа. Старый код делал b64decode от
    бинарных данных: либо падал («<fingerprint unavailable>»), либо (хуже) давал
    НЕВЕРНЫЙ SHA256, которым нельзя сверить ключ out-of-band. Теперь разбираем оба
    формата; fallback — `get_base64()` (base64-строка в обеих версиях paramiko).
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
            blob = raw  # paramiko >= 5: wire-формат — сразу SHA256'им его
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
    """Политика ключей хоста для `SSHClient.set_missing_host_key_policy()`.

    Хранение доверенных ключей — файл known_hosts (формат paramiko.HostKeys).
    Новый хост: ключ принимается и фиксируется. Изменение сохранённого ключа:
    connect() прерывается с BadHostKeyException ещё до вызова check().
    """

    def __init__(self, hostname: str = "", port: int = 22):
        self.hostname = (hostname or "").strip()
        try:
            self.port = max(1, min(65535, int(port or 22)))
        except (TypeError, ValueError):
            self.port = 22
        self._store = None            # ленивая paramiko.host_keys.HostKeys
        self._load_failed = False     # True, если файл есть, но не загрузился
        self.accepted_new_key = False  # True: в этой сессии принят ключ нового хоста
        self.last_fingerprint = ""     # его отпечаток (для сообщения пользователю)

    # ── known_hosts store ────────────────────────────────────

    def _entry_name(self) -> str:
        """Имя записи в known_hosts: host или [host]:port для нестандартного порта."""
        if not self.hostname:
            return "unknown"
        return f"[{self.hostname}]:{self.port}" if self.port != 22 else self.hostname

    def load_store(self):
        """Загрузить known_hosts в память (ленивый импорт paramiko)."""
        if self._store is None:
            store = _pk_hostkeys.HostKeys()
            path = get_known_hosts_path()
            self._load_failed = False
            try:
                store.load(path)
            except FileNotFoundError:
                # Файла ещё нет — нормальный первый запуск, пустое хранилище ок.
                pass
            except Exception as e:
                # AUDIT v0.9.5.5 (безопасность #2): файл ЕСТЬ, но повреждён —
                # работаем в памяти с пустым хранилищем, но save_store() запрещён,
                # иначе первое же TOFU-добавление затрёт все зафиксированные ключи.
                self._load_failed = True
                log = _log()
                if log:
                    log.warning(f"known_hosts file not loaded from {path}: {e}")
            self._store = store
        return self._store

    def save_store(self) -> bool:
        """Сохранить known_hosts на диск. False при ошибке (соединение не роняем)."""
        if self._load_failed:
            # Не затираем повреждённый файл: пусть пользователь восстановит его вручную.
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
        """Подключить политику и известные ключи к SSHClient перед connect()."""
        client.set_missing_host_key_policy(self)
        store = self.load_store()
        # paramiko 5.0: SSHClient.add_host_key() удалён — пишем в client.get_host_keys().
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

    # ── интерфейс paramiko HostKeyPolicy ─────────────────────

    def missing_host_key(self, client, hostname, key):
        """Первое подключение к хосту: принять ключ, залогировать отпечаток, сохранить."""
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
        # save — best effort: соединение не зависит от записи в файл, но без неё
        # pinning при следующем запуске будет потерян.
        self.save_store()

    def check(self, hostname, key):
        """Защитный метод.

        В актуальном paramiko расхождение ключей уже вызывает BadHostKeyException
        внутри connect(), до обращения к политике; этот метод — страховка на случай
        других версий/путей вызова.
        """
        import paramiko
        store = self.load_store()
        entry = store.get(hostname) or store.get(f"[{hostname}]:{self.port}")
        if entry is None:
            return  # хост неизвестен — сработает missing_host_key
        expected = entry.get(key.get_name())
        if expected is not None and expected.asbytes() != key.asbytes():
            raise paramiko.SSHException(
                f"Host key for {hostname} changed (possible MITM attack). "
                f"Expected {fingerprint(expected)}, got {fingerprint(key)}."
            )
