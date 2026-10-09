# -*- coding: utf-8 -*-
"""SSH Map example plugin — the Certificate Monitor (the first example that NEVER touches SSH).

This file is an EXAMPLE, not a shipped plugin (see `examples/README.md`): copy it into
`~/.sshmap/plugins/` and use "Plugins → Reload". Its fact does NOT come from `ctx.run_command` and
it needs no SSH at all — which is exactly when a certificate fact matters, because a host whose SSH
is down can still serve TLS. `status_probe(node)` reads this plugin's OWN config (a port per node,
or one default), opens a TLS connection from the machine running SSHMap with the standard library
(`ssl` / `socket` — no dependency, no core import) and reports `("warn", …)` under a horizon. Two
rules belong to it: an unreachable port or a refused handshake is **"no data"** (`None`), because a
firewall is not an expiring certificate, and the connector is an INJECTABLE module attribute
(`CONNECTOR`), so the gate drives this file against a canned endpoint instead of the network. The
handshake is bounded by `PROBE_TIMEOUT_S`, inside the core's `status_probe` budget."""

import json
import os
import socket
import ssl
import time
from typing import Optional

MANIFEST = {
    "name": "certificates",
    "version": "1.0",
    "api_version": 1,
    "description": "Warns when the TLS certificate of a server expires inside the configured horizon",
}

CONFIG_NAME = "certificates.json"
DEFAULT_PORT = 443
DEFAULT_HORIZON_DAYS = 21
PORT_RANGE = (1, 65535)
HORIZON_RANGE = (1, 3650)
DAY_SECONDS = 86400.0
MAX_DETAIL_CHARS = 120
# The core ABANDONS one plugin's `status_probe` after 1500 ms, so a plugin that opens its own
# socket sizes it to that budget instead of the 30 s a command may take.
PROBE_TIMEOUT_S = 1.0


# ── the plugin's own settings ─────────────────────────────────────────────────────
# API v1 registers no settings section, so a plugin keeps its settings in ITS own file beside
# its data (`PLUGINS.md` §7): `default_port` and `horizon_days` are global, `nodes` overrides
# the port for one node by its ID **or** its host.

def config_path() -> str:
    """`~/.sshmap/plugins/certificates.json` — the plugin's own settings file."""
    return os.path.join(os.path.expanduser("~"), ".sshmap", "plugins", CONFIG_NAME)


def clean_port(value) -> Optional[int]:
    """A usable TCP port, or None (a string port is accepted, junk is not)."""
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return port if PORT_RANGE[0] <= port <= PORT_RANGE[1] else None


def load_config() -> dict:
    """The stored settings, validated: `{"default_port": 443, "horizon_days": 21, "nodes": {…}}`.

    A missing, unreadable or foreign file answers the shipped defaults (the plugin then checks
    every node on 443 with a 21-day horizon) — a broken settings file costs the tuning, never the
    run. Every `nodes` entry is validated on read, so a junk port is dropped instead of guessed.
    """
    try:
        with open(config_path(), encoding="utf-8") as handle:
            document = json.load(handle)
    except Exception:                       # missing, unreadable, not JSON — all "no settings"
        document = {}
    if not isinstance(document, dict):
        document = {}
    port = clean_port(document.get("default_port")) or DEFAULT_PORT
    try:
        horizon = int(document.get("horizon_days"))
    except (TypeError, ValueError):
        horizon = DEFAULT_HORIZON_DAYS
    if not HORIZON_RANGE[0] <= horizon <= HORIZON_RANGE[1]:
        horizon = DEFAULT_HORIZON_DAYS
    nodes = {}
    for key, value in (document.get("nodes") or {}).items():
        good = clean_port(value)
        if str(key).strip() and good is not None:
            nodes[str(key).strip()] = good
    return {"default_port": port, "horizon_days": horizon, "nodes": nodes}


def port_for(node, config=None) -> int:
    """The port to check for ONE node: its own entry (by ID, then by host), else the default."""
    settings = load_config() if config is None else config
    for key in (str(getattr(node, "id", "") or "").strip(),
                str(getattr(node, "host", "") or "").strip()):
        if key and key in settings["nodes"]:
            return int(settings["nodes"][key])
    return int(settings["default_port"])


# ── the TLS door (the ONE injectable seam of this plugin) ─────────────────────────

def default_connector(host: str, port: int, timeout: float = PROBE_TIMEOUT_S):
    """The peer certificate of `<host>:<port>` — `ssl` + `socket`, from THIS machine.

    The context is the shipped VALIDATING one, so a certificate the local trust store refuses is
    a REFUSED HANDSHAKE and the caller answers "no data": this plugin reports an expiry inside a
    horizon, it does not invent a trust verdict of its own.
    """
    context = ssl.create_default_context()
    with socket.create_connection((str(host), int(port)), timeout=float(timeout)) as raw:
        with context.wrap_socket(raw, server_hostname=str(host)) as tls:
            return tls.getpeercert()


# The seam the tests replace: a canned endpoint instead of the network.
CONNECTOR = default_connector


def not_after_seconds(certificate) -> Optional[float]:
    """The `notAfter` of a peer certificate as a POSIX timestamp — None for a foreign value (PURE).

    The ONE reader of the ASN.1 timestamp (`ssl.cert_time_to_seconds()`, the standard library's
    own), so the days and the verdict below cannot disagree about what the date IS.
    """
    if not isinstance(certificate, dict):
        return None
    not_after = str(certificate.get("notAfter") or "").strip()
    if not not_after:
        return None
    try:
        return float(ssl.cert_time_to_seconds(not_after))
    except Exception:                       # noqa: BLE001 — a foreign date is "no data"
        return None


def days_left(certificate, now: Optional[float] = None) -> Optional[int]:
    """The whole days between now and `notAfter`, or None when the certificate has no usable date.

    The count is truncated TOWARD ZERO: a certificate that expired five minutes ago is 0 whole days
    past its date, never "1 day ago", and `has_expired()` is the verdict that tells the two `0`
    cases apart. The clock is an argument, so the rule is testable without waiting for a
    certificate to age.
    """
    expiry = not_after_seconds(certificate)
    if expiry is None:
        return None
    moment = time.time() if now is None else float(now)
    return int((expiry - moment) / DAY_SECONDS)


def has_expired(certificate, now: Optional[float] = None) -> Optional[bool]:
    """Is the certificate PAST its `notAfter`? — None when it carries no usable date (PURE).

    The sign `days_left()` cannot carry: a truncated day count is 0 on BOTH sides of the boundary,
    so the card needs this second fact to say "expires today" or "expired today". The same clock
    argument and the same "a foreign value is no data" rule.
    """
    expiry = not_after_seconds(certificate)
    if expiry is None:
        return None
    return expiry <= (time.time() if now is None else float(now))


def detail_text(days: int, port: int, expired: bool = False) -> str:
    """`"certificate expires in 12 days (443/tcp)"` — the ONE line the card carries.

    `expired` is the verdict of `has_expired()` and it only matters at `days == 0`, the day the two
    sentences meet: a certificate still valid today expires today, one already past its date does
    not.
    """
    if days < 0:
        text = f"certificate expired {abs(int(days))} day(s) ago ({int(port)}/tcp)"
    elif days == 0 and expired:
        text = f"certificate expired today ({int(port)}/tcp)"
    elif days == 0:
        text = f"certificate expires today ({int(port)}/tcp)"
    else:
        text = f"certificate expires in {int(days)} day(s) ({int(port)}/tcp)"
    return text[:MAX_DETAIL_CHARS]


# ── the hook ──────────────────────────────────────────────────────────────────────

def status_probe(node):
    """`("warn", "<days> days left")` under the horizon, and `None` for everything else.

    This is the counter-example the folder needs: it opens no SSH connection, so it has a verdict
    about a host the SSH probe cannot reach. The rules it follows are the ones a probe lives by —
    it answers inside the core's budget (`PROBE_TIMEOUT_S`), it never raises (an unreachable port,
    a refused handshake, a socket left open by a firewall and a certificate without a date are all
    "no data"), and a certificate that is comfortably valid is `None`: the plugin reports what the
    user has to act on, never a reassurance the SSH probe already gave.
    """
    host = str(getattr(node, "host", "") or "").strip()
    if not host:
        return None
    settings = load_config()
    port = port_for(node, settings)
    try:
        certificate = CONNECTOR(host, port, PROBE_TIMEOUT_S)
    except Exception:                       # noqa: BLE001 — no connection, no verdict
        return None
    remaining = days_left(certificate)
    if remaining is None or remaining > int(settings["horizon_days"]):
        return None
    return ("warn", detail_text(remaining, port, expired=bool(has_expired(certificate))))
