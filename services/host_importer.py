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
import threading
from typing import Dict, List, Optional

from PySide6.QtCore import QThread, Signal


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


class HostResolverThread(QThread):
    """v1.1.2RC2 (N6): пакетный DNS-резолв импорта из TXT вне GUI-потока.

    Файл с десятками имён при недоступном резолвере не должен замораживать
    интерфейс: каждый getaddrinfo() блокирует до таймаута резолвера, поэтому
    весь список резолвится в отдельном потоке (паттерн _ProbeThread из
    services/status_checker.py). Прогресс — сигнал progress(done, total) для
    статус-бара; итог — resolved_map(dict): {имя: IP или None}.

    Отмена: stop() выставляет threading.Event — цикл выходит между именами
    (текущий getaddrinfo доживает свой таймаут); в этом случае resolved_map
    приходит частичным, отсутствующие имена потребитель трактует как «не
    резолвлено» (ip="").
    """

    progress = Signal(int, int)   # (done, total) — для статус-бара
    resolved_map = Signal(dict)   # {имя: IP или None}

    def __init__(self, hostnames, parent=None):
        super().__init__(parent)
        self._hostnames = list(hostnames)
        self._cancel = threading.Event()

    def stop(self):
        """Запросить отмену (проверяется между именами)."""
        self._cancel.set()

    def run(self):
        result: Dict[str, Optional[str]] = {}
        total = len(self._hostnames)
        for i, name in enumerate(self._hostnames, start=1):
            if self._cancel.is_set():
                break  # отмена (stop при закрытии окна) — не продолжаем резолв
            try:
                result[name] = resolve_host(name)
            except Exception:
                result[name] = None  # резолв не должен ронять поток
            self.progress.emit(i, total)
        self.resolved_map.emit(result)


# v1.0-fix (audit #14): удалены мёртвые build_server_data() и import_from_text() —
# нигде не вызывались (фактический импорт в MainWindow._import_servers собирает
# ServerData инлайном: там же дедупликация по существующим узлам карты), а
# аннотация/докстринг import_from_text расходились с кодом. Оставлены реально
# используемые parse_hosts_file / is_ip_address / resolve_host; v1.1.2RC2 (N6):
# processEvents при длинном резолве заменён HostResolverThread (вне GUI-потока).
