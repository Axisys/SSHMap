"""Host Importer — bulk import of servers from a text file (v0.9.5.5).

File format: one server per line — an IP address or a host DNS name.
Empty lines and comments (# ...) are ignored.

Logic:
  • a line looks like an IPv4/IPv6 → take it as-is (host = IP);
  • otherwise it is a DNS name → resolve it via socket.getaddrinfo(); on success
    the found IP is stored in the node's `ip` field, and `host` stays the name
    (the SSH connection will use the name from then on); on failure the node is
    still created with host=name, ip="" — the user will sort it out manually.

Passwords/users are not touched — the user sets them up after the import.
"""

import ipaddress
import socket
import threading
from typing import Dict, List, Optional

from PySide6.QtCore import QThread, Signal


def parse_hosts_file(text: str) -> List[str]:
    """Parse the file text: non-empty lines without '#' and '//' (trimmed)."""
    hosts = []
    for line in text.splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#") or entry.startswith("//"):
            continue
        # A line may be "host ip" separated by a tab/space — take the first word
        entry = entry.split()[0]
        hosts.append(entry)
    return hosts


def is_ip_address(entry: str) -> bool:
    """True if the string is a valid IPv4/IPv6 address."""
    try:
        ipaddress.ip_address(entry)
        return True
    except ValueError:
        return False


def resolve_host(hostname: str) -> Optional[str]:
    """DNS-resolve a name → an IP string or None."""
    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        for family, _stype, _proto, _canonname, sockaddr in infos:
            addr = sockaddr[0]
            # For an IPv6 link-local address, strip the %zone — not needed in the ip field
            return addr.split("%")[0]
        return None
    except OSError:
        return None


class HostResolverThread(QThread):
    """v1.1.2RC2 (N6): batch DNS resolution of a TXT import, outside the GUI thread.

    A file with dozens of names must not freeze the UI when the resolver is
    unreachable: each getaddrinfo() blocks until the resolver timeout, so the
    whole list is resolved in a separate thread (the _ProbeThread pattern from
    services/status_checker.py). Progress — the progress(done, total) signal for
    the status bar; the result — resolved_map(dict): {name: IP or None}.

    Cancellation: stop() sets a threading.Event — the loop exits between names
    (the current getaddrinfo runs out its timeout); in that case resolved_map
    arrives partial, and the consumer treats the missing names as "not resolved"
    (ip="").
    """

    progress = Signal(int, int)   # (done, total) — for the status bar
    resolved_map = Signal(dict)   # {name: IP or None}

    def __init__(self, hostnames, parent=None):
        super().__init__(parent)
        self._hostnames = list(hostnames)
        self._cancel = threading.Event()

    def stop(self):
        """Request cancellation (checked between names)."""
        self._cancel.set()

    def run(self):
        result: Dict[str, Optional[str]] = {}
        total = len(self._hostnames)
        for i, name in enumerate(self._hostnames, start=1):
            if self._cancel.is_set():
                break  # cancellation (stop on window close) — stop resolving
            try:
                result[name] = resolve_host(name)
            except Exception:
                result[name] = None  # a resolution failure must not kill the thread
            self.progress.emit(i, total)
        self.resolved_map.emit(result)


# v1.0-fix (audit #14): removed the dead build_server_data() and import_from_text() —
# they were never called anywhere (the actual import in MainWindow._import_servers
# builds ServerData inline: deduplication against existing map nodes happens there
# too), and the annotation/docstring of import_from_text disagreed with the code.
# The actually used parse_hosts_file / is_ip_address / resolve_host are kept;
# v1.1.2RC2 (N6): processEvents during a long resolution is replaced by
# HostResolverThread (outside the GUI thread).
