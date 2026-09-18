# -*- coding: utf-8 -*-
"""SSH Map example plugin — the Disk Space Monitor (the first USEFUL example).

This file is an EXAMPLE, not a shipped plugin (see `examples/README.md`): copy it into
`~/.sshmap/plugins/` and use `Plugins → Reload`. It demonstrates the one design every
real plugin needs — **a collector and a reporter are two different hooks**:

* `run_on_nodes(nodes, ctx)` — the COLLECTOR. `Plugins → "Run on selected servers"`
  (or a command of your own that calls the same hook) runs `df -hP` on every node the
  user selected through `ctx.run_command()`, parses the WORST percentage per node,
  writes the answer into this plugin's own cache atomically and reports a line in the
  status bar. The SSH work is the CORE's: credentials, transport, per-node timeout and
  "one node's failure never stops the others" all live in the core (`PLUGINS.md` §5) —
  this plugin owns no SSH code at all.
* `status_probe(node)` — the REPORTER. It runs inside the ORDINARY status round: one
  call per node, every `status_interval_sec`, on a pool worker. It therefore reads the
  cache and NOTHING else — an SSH call here would hammer the servers and would bypass
  the core's credential resolver. The core merges the answer with the SSH probe and
  keeps the WORSE by severity, so a full disk turns the card `warn` even while the SSH
  probe says `online`, and a full disk can never hide an `offline` host.

What a user sees in API v1: the card turns **`warn`** and the tooltip carries the
offending mount point and its percentage. A plugin CANNOT recolour a card or add a tag —
`PluginNode` is a frozen `{id, alias, host, port, user}` and the context has no
node-mutation service, by design (`PLUGINS.md` §6); that limitation is recorded in the
ROADMAP as the argued candidate for API v2.

**A plugin never imports the core** (`modules.*`, `i18n.*`, `ui.*`): an installed
application does not have this repository on `sys.path`. Everything arrives through
`ctx` and the hook arguments, and the plugin's own strings are the AUTHOR's
(`PLUGINS.md` §7).
"""

import json
import os
import tempfile
import time
from typing import Dict, Optional, Tuple

MANIFEST = {
    "name": "disk_monitor",
    "version": "1.0",
    "api_version": 1,
    "description": "Checks the disk usage of the selected servers and warns from its own cache",
}

COMMAND = "df -hP"          # the POSIX form: a fixed column layout and a decimal-free Use%
WARN_PERCENT = 90           # a filesystem filled to (or above) this is worth a warning
STALE_SECONDS = 3600        # a cache older than this is not an opinion any more
MAX_RECORDS = 50            # the cache is a hint, not a database
CACHE_NAME = "disk_monitor.state.json"
CACHE_VERSION = 1

# Pseudo-filesystems: full (or sizeless) by design, so a percentage of them means nothing.
PSEUDO_FILESYSTEMS = frozenset({
    "tmpfs", "devtmpfs", "overlay", "none", "udev", "shm", "squashfs", "ramfs",
    "proc", "sysfs", "cgroup", "cgroup2",
})


# ── the cache: the plugin's own data, next to the plugin folder ───────────────────
# A `config.json` key would be a core service a plugin does not have (PLUGINS.md §6
# forbids writing the application's config), so the collector owns one small file in
# `~/.sshmap/plugins/` — and every path through it is wrapped: a disposable cache must
# never break a probe round or a run.

def cache_path() -> str:
    """`~/.sshmap/plugins/disk_monitor.state.json` — the plugin's own cache file."""
    return os.path.join(os.path.expanduser("~"), ".sshmap", "plugins", CACHE_NAME)


def parse_percent(value) -> Optional[int]:
    """`"92%"` → 92, `"92,5%"` → 92, clamped to 0..100; None when it is not a percentage.

    `df -hP` promises a decimal-free integer, so the decimal branch is only a guard for
    a locale that ignored `-P`; a value that is not a number at all (a header's `Use%`,
    a truncated line) yields None and the caller skips the line.
    """
    text = ("" if value is None else str(value)).strip().rstrip("%").strip().replace(",", ".")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return max(0, min(100, int(number)))


def parse_df(text) -> Optional[Tuple[int, str]]:
    """The WORST real filesystem of a `df -hP` answer → `(percent, mount point)` or None.

    One function, no socket: that is what makes the whole parsing testable. It walks the
    lines, skips anything that is not a six-column row (the header, a `df:` warning, a
    truncated line), skips the pseudo-filesystems above, and keeps the highest percentage
    — the worst mount is what a user cares about. `-P` writes the mount point LAST, so a
    directory with a SPACE in its name stays in one piece (`/mnt/my data`).
    """
    worst: Optional[Tuple[int, str]] = None
    for raw in str(text or "").splitlines():
        parts = raw.split(None, 5)          # 6 columns; the 6th is "Mounted on" (may hold spaces)
        if len(parts) < 6:
            continue
        filesystem, _size, _used, _avail, use, mount = parts
        if filesystem.strip().lower() in PSEUDO_FILESYSTEMS:
            continue
        percent = parse_percent(use)
        if percent is None:
            continue
        mount = mount.strip() or filesystem.strip()
        if worst is None or percent > worst[0]:
            worst = (percent, mount)
    return worst


def _clean_record(record) -> Optional[dict]:
    """One stored record, validated (`None` for junk — a broken entry is dropped, not fatal)."""
    if not isinstance(record, dict):
        return None
    percent = parse_percent(record.get("percent"))
    if percent is None:
        return None
    try:
        stamp = float(record.get("ts") or 0.0)
    except (TypeError, ValueError):
        stamp = 0.0
    return {"alias": str(record.get("alias") or ""), "percent": percent,
            "mount": str(record.get("mount") or ""), "ts": stamp}


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
    tooltip line, never a run). The merge is what makes a per-node collection cheap: a
    node that was not part of this round keeps its previous answer until it goes stale.
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
        handle, temp_path = tempfile.mkstemp(prefix=".disk_monitor-", suffix=".tmp", dir=folder)
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


# ── the hooks ─────────────────────────────────────────────────────────────────────

def run_on_nodes(nodes, ctx):
    """The COLLECTOR: `df -hP` on every node the user gave us, then ONE cache write.

    The hook runs on a managed worker thread (PLUGINS.md §6) and the SSH work goes
    through `ctx.run_command()`, so the credentials, the transport, the per-node timeout
    and "one node's failure never stops the others" are the core's business. A node
    without an answer is a log line: the status bar counts what really answered.
    """
    records = list(nodes or [])
    if not records:
        ctx.status("disk: nothing selected", 3000)
        return
    collected: Dict[str, dict] = {}
    failures = []

    def on_result(node, result):
        """One node's answer (or its failure) — a failure is a result for THAT node."""
        if result.error or result.exit_code != 0:
            failures.append(node.id)
            ctx.log(f"disk: {node.label()} — no answer "
                    f"({result.error or 'exit code ' + str(result.exit_code)})")
            return
        worst = parse_df(result.output)
        if worst is None:
            failures.append(node.id)
            ctx.log(f"disk: {node.label()} — no filesystem in the answer of `{COMMAND}`")
            return
        percent, mount = worst
        collected[node.id] = {"alias": node.alias, "percent": percent,
                              "mount": mount, "ts": time.time()}
        ctx.log(f"disk: {node.label()} — {mount} {percent}%")

    def on_finished(results):
        """The whole round: one atomic cache write, then the line the user reads."""
        saved = save_cache(collected) if collected else False
        over = [r for r in collected.values() if r["percent"] >= WARN_PERCENT]
        ctx.status(f"disk: {len(collected)} node(s), {len(over)} over the threshold", 5000)
        if collected and not saved:
            ctx.log("disk: the cache could not be written — the card keeps the SSH status")
        if failures:
            ctx.log(f"disk: {len(failures)} node(s) without an answer: "
                    f"{', '.join(sorted(failures))}")

    if not ctx.run_command(records, COMMAND, on_result=on_result, on_finished=on_finished):
        ctx.log("disk: run_command() refused the call (no nodes or an empty command)")
        ctx.status("disk: nothing to do", 3000)


def status_probe(node):
    """The REPORTER: `("warn", "<mount> <n>% (threshold 90)")`, or None for "no opinion".

    Reads the cache and NOTHING else: this runs for EVERY node on EVERY status round,
    inside the parallel probe pool, so an SSH (or file-system) call here would hammer the
    servers and bypass the core's credential resolver. None — the node is unknown, the
    cache is missing, the record is stale, or nothing is over the threshold. The core
    keeps the worse of the two statuses, so a warning is visible over an `online` probe
    and can never hide an `offline` host.
    """
    record = fresh_record(getattr(node, "id", ""))
    if record is None or record["percent"] < WARN_PERCENT:
        return None
    return ("warn", f"{record['mount']} {record['percent']}% (threshold {WARN_PERCENT})")
