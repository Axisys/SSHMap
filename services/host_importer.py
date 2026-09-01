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
from typing import List, Optional


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


# v1.0-fix (audit #14): удалены мёртвые build_server_data() и import_from_text() —
# нигде не вызывались (фактический импорт в MainWindow._import_servers собирает
# ServerData инлайном: там же дедупликация по существующим узлам карты и
# processEvents при длинном резолве), а аннотация/докстринг import_from_text
# расходились с кодом. Оставлены реально используемые parse_hosts_file /
# is_ip_address / resolve_host.
