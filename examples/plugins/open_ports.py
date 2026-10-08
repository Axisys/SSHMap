# -*- coding: utf-8 -*-
"""SSH Map example plugin — the Open Ports Monitor: collect `ss -tulpn`, report from the cache.

This file is an EXAMPLE (see `examples/README.md`), shaped like `disk_monitor.py`: a COLLECTOR and a
REPORTER are two different hooks. `run_on_nodes(nodes, ctx)` runs `ss -tulpn` on every selected node
through the core's `ctx.run_command()` (credentials, transport, the per-node timeout and "one failure
never stops the others" are the CORE's), parses the listening sockets, writes the answer into this
plugin's own atomic cache and reports it TWICE into the Plugins window — the counts, then the whole port
list of the node (`log_text()`), which that window EXPORTS to a text file. `status_probe()` runs inside
the ORDINARY status round and reads that cache and NOTHING else: the tooltip gets the reachable ports
and a watchlisted port REACHABLE from the network turns the card `warn` (the core merges the two
opinions by severity, so a warning never hides an `offline` host). A plugin never imports the core
(PLUGINS.md §6); the cache is `~/.sshmap/plugins/open_ports.state.json` — delete it freely."""

import json
import os
import re
import tempfile
import time
from typing import Dict, List, Optional, Tuple

MANIFEST = {
    "name": "open_ports",
    "version": "1.0",
    "api_version": 1,
    "description": "Collects the listening sockets of the selected servers with `ss -tulpn` and reports them",
}

COMMAND = "ss -tulpn"         # listening TCP + UDP sockets; without -H the first line is a header
STALE_SECONDS = 3600          # a cache older than this is not an opinion any more
MAX_RECORDS = 50              # the cache is a hint, not a database
MAX_PORTS_PER_NODE = 64       # a node with hundreds of sockets is a data point, not a report
MAX_DETAIL_PORTS = 8          # the tooltip line stays readable
MAX_WARN_PORTS = 4            # the warning names the worst few, then counts the rest
CACHE_NAME = "open_ports.state.json"
CACHE_VERSION = 1

# A port REACHABLE from the network that is on this list is worth a warning: a database, a cache or a
# remote-admin service is not a public one. A loopback socket is never a hit, whatever the port —
# `127.0.0.1:3306` is exactly how a database should be bound.
WATCH_PORTS = frozenset({21, 23, 111, 445, 1433, 1521, 2049, 2375, 2376, 3306, 3389, 5432, 5601,
                         5900, 6379, 9200, 9300, 11211, 27017})

# The `State` field of a socket row: `-l` already filtered the round, so the field is READ for the
# column LAYOUT (a build that leaves it blank shifts every column by one) and never filters a row.
SS_STATES = frozenset({
    "LISTEN", "UNCONN", "ESTAB", "IDLE", "BOUND", "CLOSE", "CLOSED", "CLOSING",
    "SYN-SENT", "SYN-RECV", "NEW-SYN-RECV", "TIME-WAIT", "CLOSE-WAIT", "LAST-ACK",
    "FIN-WAIT-1", "FIN-WAIT-2",
})

# How far a binding reaches: `global` = every interface, `specific` = one interface address,
# `local` = loopback only. The rank decides which of two bindings of ONE port is kept.
SCOPE_RANK = {"local": 0, "specific": 1, "global": 2}

GLOBAL_HOSTS = frozenset({"0.0.0.0", "*", "::", "0:0:0:0:0:0:0:0"})
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
LOOPBACK_PREFIXES = ("127.",)

# `ss` resolves a port to its SERVICE NAME unless `-n` is given, so a build that prints `ssh` instead
# of `22` must not lose the row: the table is a guard (the same role `parse_percent`'s decimal branch
# plays in the disk monitor), not a dictionary.
SERVICE_PORTS = {
    "ftp": 21, "ssh": 22, "telnet": 23, "smtp": 25, "domain": 53, "http": 80, "pop3": 110,
    "rpcbind": 111, "ntp": 123, "imap": 143, "snmp": 161, "ldap": 389, "https": 443,
    "smtps": 465, "submission": 587, "ldaps": 636, "imaps": 993, "pop3s": 995, "mssql": 1433,
    "oracle": 1521, "nfs": 2049, "docker": 2375, "mysql": 3306, "rdp": 3389, "postgresql": 5432,
    "vnc": 5900, "redis": 6379, "http-alt": 8080, "elasticsearch": 9200, "memcache": 11211,
    "mongod": 27017,
}

# The program name inside `users:(("sshd",pid=987,fd=3))` — the FIRST quoted string of the column.
PROCESS_RE = re.compile(r'"([^"]+)"')


# ── the cache: the plugin's own data, next to the plugin folder ───────────────────
# A `config.json` key would be a core service a plugin does not have (PLUGINS.md §6 forbids
# writing the application's config), so the collector owns one small file in `~/.sshmap/plugins/`
# — and every path through it is wrapped: a disposable cache must never break a probe round.

def cache_path() -> str:
    """`~/.sshmap/plugins/open_ports.state.json` — the plugin's own cache file."""
    return os.path.join(os.path.expanduser("~"), ".sshmap", "plugins", CACHE_NAME)


# ── parsing `ss -tulpn` (pure functions, no socket) ───────────────────────────────

def parse_port(value) -> Optional[int]:
    """`"22"` / `"https"` → 22 / 443; None when the token is neither a number nor a known service.

    A port outside 0..65535, a peer's `*`, an empty column and a truncated line all yield
    None, and the caller skips the row instead of inventing a port.
    """
    text = ("" if value is None else str(value)).strip()
    if not text:
        return None
    if text.isdigit():
        port = int(text)
        return port if 0 <= port <= 65535 else None
    return SERVICE_PORTS.get(text.lower())


def split_endpoint(text) -> Tuple[str, str]:
    """`"0.0.0.0:22"` / `"[::]:22"` / `"*:https"` → `(host, port token)`; no port → `(text, "")`.

    The port is the LAST colon-separated field, so an IPv6 endpoint is read through its
    brackets (the form `ss` prints) and a bare `::` stays one host rather than two.
    """
    token = ("" if text is None else str(text)).strip()
    if token.startswith("[") and "]:" in token:
        host, _sep, port = token[1:].partition("]:")
        return host, port
    host, sep, port = token.rpartition(":")
    if not sep or not port:
        return token, ""
    return host, port


def host_scope(host) -> str:
    """`"global"`, `"specific"` or `"local"` (loopback only) — how far a binding reaches."""
    text = ("" if host is None else str(host)).strip().strip("[]").lower()
    if text in GLOBAL_HOSTS:
        return "global"
    if text in LOOPBACK_HOSTS or text.startswith(LOOPBACK_PREFIXES):
        return "local"
    return "specific"


def _clean_port(entry) -> Optional[dict]:
    """One socket row, validated (`None` for junk — a broken entry is dropped, not fatal)."""
    if not isinstance(entry, dict):
        return None
    try:
        port = int(entry.get("port"))
    except (TypeError, ValueError):
        return None
    if not 0 <= port <= 65535:
        return None
    scope = str(entry.get("scope") or "").lower()
    if scope not in SCOPE_RANK:
        scope = "specific"
    return {"proto": str(entry.get("proto") or "tcp").lower()[:8], "port": port,
            "address": str(entry.get("address") or "")[:64], "scope": scope,
            "process": str(entry.get("process") or "")[:64]}


def normalise_ports(entries) -> List[dict]:
    """ONE row per `(proto, port)` — the MOST EXPOSED binding wins — capped and ordered by port.

    A dual-stack listener prints two rows (`0.0.0.0:5432` and `[::]:5432`) and a socket
    bound both to a loopback and to a public address prints two more: `0.0.0.0` beside
    `127.0.0.1` IS the exposed one, so the reachable binding is what this list keeps. The
    cap drops loopback rows first (the lowest ports are what a reader scans for).
    """
    best: Dict[Tuple[str, int], dict] = {}
    for entry in entries or ():
        good = _clean_port(entry)
        if good is None:
            continue
        key = (good["proto"], good["port"])
        current = best.get(key)
        if current is None or SCOPE_RANK[good["scope"]] > SCOPE_RANK[current["scope"]]:
            best[key] = good
    ranked = sorted(best.values(), key=lambda item: (-SCOPE_RANK[item["scope"]], item["port"]))
    kept = ranked[:MAX_PORTS_PER_NODE]
    return sorted(kept, key=lambda item: (item["port"], item["proto"]))


def parse_ss(text) -> List[dict]:
    """The listening sockets of an `ss -tulpn` answer, normalised (always a list, never None).

    One function, no socket: that is what makes the whole parsing testable. It walks the
    lines, skips anything that is not a socket row (the `Netid …` header, a message `ss`
    wrote, a truncated line), reads the LOCAL endpoint from the column the `State` field
    really occupies and keeps the port the socket is bound to. The process name is a BONUS:
    `ss -p` prints it for the sockets of OTHER users only when the command runs as root.
    """
    rows: List[dict] = []
    for raw in str(text or "").splitlines():
        fields = raw.split()
        if len(fields) < 4:
            continue
        netid = fields[0].lower()
        if not netid.startswith(("tcp", "udp", "sct")):
            continue                     # the header, or a line that is not a socket at all
        index = 4 if fields[1].upper() in SS_STATES else 3
        if len(fields) <= index:
            continue
        host, port_token = split_endpoint(fields[index])
        port = parse_port(port_token)
        if port is None or not host:
            continue
        process = ""
        if len(fields) > index + 2:      # index + 1 is the PEER column
            found = PROCESS_RE.search(" ".join(fields[index + 2:]))
            process = found.group(1) if found else ""
        rows.append({"proto": netid, "port": port, "address": host,
                     "scope": host_scope(host), "process": process})
    return normalise_ports(rows)


# ── the cache: reading, merging and writing it atomically ─────────────────────────

def _clean_record(record) -> Optional[dict]:
    """One stored node record, validated (`None` for junk — a broken entry is dropped, not fatal)."""
    if not isinstance(record, dict):
        return None
    raw_ports = record.get("ports")
    ports = []
    if isinstance(raw_ports, list):
        for entry in raw_ports[:MAX_PORTS_PER_NODE]:
            good = _clean_port(entry)
            if good is not None:
                ports.append(good)
    try:
        stamp = float(record.get("ts") or 0.0)
    except (TypeError, ValueError):
        stamp = 0.0
    return {"alias": str(record.get("alias") or ""), "ports": ports, "ts": stamp}


def load_cache() -> Dict[str, dict]:
    """The stored records keyed by node id — `{}` for a missing / broken / foreign cache."""
    try:
        with open(cache_path(), encoding="utf-8") as handle:
            document = json.load(handle)
    except Exception:                       # missing, unreadable, not JSON — all "no cache"
        return {}
    if not isinstance(document, dict) or not isinstance(document.get("records"), dict):
        return {}
    clean: Dict[str, dict] = {}
    for node_id, record in document["records"].items():
        good = _clean_record(record)
        if good is not None:
            clean[str(node_id)] = good
    return clean


def _prune(records: Dict[str, dict]) -> Dict[str, dict]:
    """The `MAX_RECORDS` NEWEST records (a node that left the map must not grow the file)."""
    ordered = sorted(records.items(), key=lambda item: float(item[1].get("ts") or 0.0),
                     reverse=True)
    return dict(ordered[:MAX_RECORDS])


def save_cache(records) -> bool:
    """Merge + prune + write the cache ATOMICALLY (a temp file in the folder + `os.replace`).

    Returns False when the write failed — the caller keeps working (a lost cache costs a
    tooltip line, never a run). The merge is what makes a per-node collection cheap: a node
    that was not part of this round keeps its previous answer until it goes stale.
    """
    if not isinstance(records, dict):
        return False
    merged = load_cache()
    for node_id, record in records.items():
        good = _clean_record(record)
        if good is not None:
            merged[str(node_id)] = good
    document = {"version": CACHE_VERSION, "records": _prune(merged)}
    folder = os.path.dirname(cache_path())
    temp_path = ""
    try:
        os.makedirs(folder, exist_ok=True)
        handle, temp_path = tempfile.mkstemp(prefix=".open_ports-", suffix=".tmp", dir=folder)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
        os.replace(temp_path, cache_path())
        return True
    except Exception:                       # noqa: BLE001 — a cache is disposable
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass
        return False


def fresh_record(node_id, now: Optional[float] = None) -> Optional[dict]:
    """The record of a node, or None when it is unknown, missing or STALE."""
    record = load_cache().get(str(node_id or ""))
    if record is None:
        return None
    moment = time.time() if now is None else float(now)
    if moment - float(record.get("ts") or 0.0) > STALE_SECONDS:
        return None
    return record


# ── reading the record: the reporter's lines and the window's export line ─────────

def watch_hits(ports) -> Tuple[dict, ...]:
    """The REACHABLE sockets whose port is on `WATCH_PORTS` (loopback is never a hit)."""
    return tuple(item for item in ports or ()
                 if item.get("port") in WATCH_PORTS and item.get("scope") != "local")


def _reachable(ports) -> List[dict]:
    """The sockets bound to something other than loopback — the ones a network can reach."""
    return [item for item in ports or () if item.get("scope") != "local"]


def format_ports(ports, limit: int = MAX_DETAIL_PORTS) -> str:
    """`"22/tcp, 80/tcp, 443/tcp (+2 more)"` — the bounded list a tooltip gets."""
    shown = ", ".join(f"{item['port']}/{item['proto']}" for item in ports[:limit])
    if len(ports) > limit:
        shown += f" (+{len(ports) - limit} more)"
    return shown


def _row_text(item) -> str:
    """ONE socket in the export line, its scope MARKED: `6379/tcp redis-server (exposed)`.

    The mark is the fact the tooltip only counts (its `(+N on loopback)`), and `exposed` outranks
    `loopback` because a watchlisted port a network can REACH is what a reader acts on. The process
    name rides an `exposed` row only: `ss -p` prints it as root, and a name beside every row would
    make the line unreadable.
    """
    text = f"{item['port']}/{item['proto']}"
    if item.get("port") in WATCH_PORTS and item.get("scope") != "local":
        process = f" {item['process']}" if item.get("process") else ""
        return f"{text}{process} (exposed)"
    if item.get("scope") == "local":
        return f"{text} (loopback)"
    return text


def log_text(record, limit: int = MAX_PORTS_PER_NODE) -> str:
    """The Plugins window's DATA line for one node — the whole cached list, ready to export.

    `"3 socket(s): 22/tcp, 68/udp, 3306/tcp (loopback)"`. It is `report_text()`'s sibling and not
    its twin on purpose: the tooltip stays a glance (`MAX_DETAIL_PORTS`) while this line carries
    what the CACHE holds (`MAX_PORTS_PER_NODE`), because the window renders `ctx.log()` verbatim
    and exports it to a FILE — the reason a plugin reports its data and not only a count.
    """
    ports = list(record.get("ports") or ())
    if not ports:
        return "no listening socket"
    shown = ", ".join(_row_text(item) for item in ports[:limit])
    if len(ports) > limit:
        shown += f" (+{len(ports) - limit} more)"
    return f"{len(ports)} socket(s): {shown}"


def report_text(record) -> str:
    """The clean line: what is reachable, and how much sits on loopback.

    `"7 open: 22/tcp, 80/tcp, 443/tcp (+2 on loopback)"` / `"nothing reachable (+3 on
    loopback)"` / `"no listening socket"`.
    """
    ports = list(record.get("ports") or ())
    reachable = _reachable(ports)
    local = len(ports) - len(reachable)
    if reachable:
        text = f"{len(reachable)} open: {format_ports(reachable)}"
    else:
        text = "nothing reachable" if local else "no listening socket"
    if local:
        text += f" (+{local} on loopback)"
    return text


def warn_text(record, hits) -> str:
    """The warning line: the watchlisted ports that are reachable, then how much is open.

    `"exposed 3306/tcp (mysqld), 6379/tcp (redis-server) - 7 open"`. The bound address is
    deliberately NOT repeated here: it is in the record and the count is what a reader acts
    on; the process name is the one bonus `ss -p` offers, and it is missing without root.
    """
    named = ", ".join(f"{item['port']}/{item['proto']}"
                      + (f" ({item['process']})" if item.get("process") else "")
                      for item in hits[:MAX_WARN_PORTS])
    if len(hits) > MAX_WARN_PORTS:
        named += f" (+{len(hits) - MAX_WARN_PORTS} more)"
    return f"exposed {named} - {len(_reachable(record.get('ports')))} open"


# ── the hooks ─────────────────────────────────────────────────────────────────────

def run_on_nodes(nodes, ctx):
    """The COLLECTOR: `ss -tulpn` on every node the user gave us, then ONE cache write.

    The hook runs on a managed worker thread (PLUGINS.md §6) and the SSH work goes through
    `ctx.run_command()`, so the credentials, the transport, the per-node timeout and "one
    node's failure never stops the others" are the core's business. An answer with no socket
    row in it is a failure and not a node without ports: a host whose `ss` is missing (or is
    not allowed to list the sockets) must be visible in the log, never cached as "nothing
    open". A node without an answer is a log line and the status bar counts what answered.
    """
    records = list(nodes or [])
    if not records:
        ctx.status("ports: nothing selected", 3000)
        return
    collected: Dict[str, dict] = {}
    failures = []

    def on_result(node, result):
        """One node's answer (or its failure) — a failure is a result for THAT node."""
        if result.error or result.exit_code != 0:
            failures.append(node.id)
            ctx.log(f"ports: {node.label()} — no answer "
                    f"({result.error or 'exit code ' + str(result.exit_code)})")
            return
        ports = parse_ss(result.output)
        if not ports:
            failures.append(node.id)
            ctx.log(f"ports: {node.label()} — no socket in the answer of `{COMMAND}`")
            return
        record = {"alias": node.alias, "ports": ports, "ts": time.time()}
        collected[node.id] = record
        hits = watch_hits(ports)
        ctx.log(f"ports: {node.label()} — {len(ports)} listening socket(s), "
                f"{len(hits)} watchlisted and reachable")
        # The Plugins window renders `ctx.log()` VERBATIM and exports it to a text file, so the
        # DATA rides here too — the whole cached list, where the tooltip stays a glance.
        ctx.log(f"ports: {node.label()} — {log_text(record)}")

    def on_finished(results):
        """The whole round: one atomic cache write, then the line the user reads."""
        saved = save_cache(collected) if collected else False
        risky = sum(1 for record in collected.values() if watch_hits(record["ports"]))
        ctx.status(f"ports: {len(collected)} node(s), {risky} with a watchlisted port exposed", 5000)
        if collected and not saved:
            ctx.log("ports: the cache could not be written — the card keeps the SSH status")
        if failures:
            ctx.log(f"ports: {len(failures)} node(s) without an answer: "
                    f"{', '.join(sorted(failures))}")

    if not ctx.run_command(records, COMMAND, on_result=on_result, on_finished=on_finished):
        ctx.log("ports: run_command() refused the call (no nodes or an empty command)")
        ctx.status("ports: nothing to do", 3000)


def status_probe(node):
    """The REPORTER: the cached port list as a detail, and `warn` for an exposed watch port.

    Reads the cache and NOTHING else: this runs for EVERY node on EVERY status round, inside
    the parallel probe pool, so an SSH (or file-system) call here would hammer the servers and
    bypass the core's credential resolver. None — the node is unknown, the cache is missing or
    the record is stale ("no opinion", and the SSH probe stands). Otherwise the answer rides
    on `online` (the worst kind the cache can justify: it knows sockets, not reachability),
    which the core merges by severity, so a warning is visible and an `offline` host is never
    masked.
    """
    record = fresh_record(getattr(node, "id", ""))
    if record is None:
        return None
    hits = watch_hits(record.get("ports"))
    if hits:
        return ("warn", warn_text(record, hits))
    return ("online", report_text(record))
