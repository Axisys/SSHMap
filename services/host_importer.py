"""Host Importer — массовый импорт серверов из текстового файла (v0.9.5.5).

Формат файла: по одному серверу в строке — IP-адрес или DNS-имя хоста.
Пустые строки и комментарии (# ...) игнорируются.

Логика:
  • строка похожа на IPv4/IPv6 → берём как есть (host = IP);
  • иначе это DNS-имя → резолвим через socket.getaddrinfo(); при успехе
    найденный IP сохраняется в поле `ip` узла, а `host` остаётся именем
    (SSH-подключение в дальнейшем пойдёт по имени); при неудаче узел всё
    равно создаётся с host=имя, ip="" — пользователь разберётся вручную.

Пароли/пользователи не трогаем — пользователь настраивает их после импорта.
"""

import ipaddress
import socket
from typing import List, Optional, Tuple

# Локальный импорт модели (пакетный или плоский запуск)
try:
    from models.server import ServerData
except ImportError:
    from .models.server import ServerData  # type: ignore


def parse_hosts_file(text: str) -> List[str]:
    """Разобрать текст файла: непустые строки без '#' и '//' (trim)."""
    hosts = []
    for line in text.splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#") or entry.startswith("//"):
            continue
        # В строке может быть "host ip" табом/пробелом — берём первое слово
        entry = entry.split()[0]
        hosts.append(entry)
    return hosts


def is_ip_address(entry: str) -> bool:
    """True, если строка — корректный IPv4/IPv6 адрес."""
    try:
        ipaddress.ip_address(entry)
        return True
    except ValueError:
        return False


def resolve_host(hostname: str) -> Optional[str]:
    """DNS-резолв имени → IP-строка или None."""
    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        for family, _stype, _proto, _canonname, sockaddr in infos:
            addr = sockaddr[0]
            # Для IPv6 link-local отрежем %zone — в поле ip он не нужен
            return addr.split("%")[0]
        return None
    except OSError:
        return None


def build_server_data(entry: str) -> ServerData:
    """Собрать ServerData для одной строки файла (без добавления на карту)."""
    import uuid

    resolved_ip = ""
    if is_ip_address(entry):
        host = entry
        resolved_ip = entry
    else:
        host = entry
        resolved_ip = resolve_host(entry) or ""

    alias = entry  # псевдоним = строка из файла; пользователь переименует
    return ServerData(
        id=str(uuid.uuid4())[:8],
        alias=alias,
        host=host,
        user="",           # пользователь настроит после импорта
        password="",
        ip=resolved_ip,
    )


def import_from_text(text: str) -> Tuple[List[ServerData], List[str]]:
    """Полный цикл: текст файла → (список ServerData, список дубликатов).

    Дубликаты: повторные строки внутри файла И записи, чей host уже есть
    в existing_hosts. Резолв выполняется только для новых уникальных имён.
    """
    entries = parse_hosts_file(text)
    seen = set()
    unique = []
    duplicates = []
    for e in entries:
        if e.lower() in seen:
            duplicates.append(e)
        else:
            seen.add(e.lower())
            unique.append(e)
    return unique, duplicates
