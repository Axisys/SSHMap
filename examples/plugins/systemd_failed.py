# -*- coding: utf-8 -*-
"""SSH Map example plugin — the Systemd Failed Monitor (the smallest honest monitor).

This file is an EXAMPLE, not a shipped plugin (see `examples/README.md`): copy it into
`~/.sshmap/plugins/` and use "Plugins → Reload". ONE command, ONE count, ONE detail line:
`run_on_nodes(nodes, ctx)` COLLECTS `systemctl --failed` per node through `ctx.run_command()` and
merges the answer into this plugin's own atomic cache, while `status_probe(node)` REPORTS from that
cache and NOTHING else (no SSH inside a probe).

The reporter answers `warn` with the first unit names while units have failed and **`None` for a
count of zero** — "no opinion" rather than `online`, so a plugin can never BRIGHTEN a card the SSH
probe marked down, and a host without systemd (no `systemctl` on `PATH`, a container) is "no data".
A plugin never imports the core and its strings are the AUTHOR's (`PLUGINS.md` §7)."""

import json
import os
import tempfile
import time
from typing import Dict, List, Optional

MANIFEST = {
    "name": "systemd_failed",
    "version": "1.0",
    "api_version": 1,
    "description": "Counts the failed systemd units of the selected servers and warns from its own cache",
}

COMMAND = "systemctl --failed --no-legend --plain"
CACHE_NAME = "systemd_failed.state.json"
CACHE_VERSION = 1
STALE_SECONDS = 3600        # a cache older than this is not an opinion any more
MAX_RECORDS = 50            # the cache is a hint, not a database
MAX_UNITS = 5               # the unit names the detail line carries

# A unit name carries its TYPE as the suffix, and that is what tells a row of the answer apart from
# a diagnostic line ("Failed to connect to bus", "System has not been booted with systemd").
UNIT_SUFFIXES = (".service", ".socket", ".device", ".mount", ".automount", ".swap",
                 ".target", ".timer", ".path", ".slice", ".scope")


# ── the cache: the plugin's own data, next to the plugin folder ───────────────────
# `config.json` is the CORE's file and a plugin has no service to write it (`PLUGINS.md` §6),
# so the collector owns one small file in `~/.sshmap/plugins/` — and every path through it
# is wrapped: a disposable cache must never break a probe round or a run.

def cache_path() -> str:
    """`~/.sshmap/plugins/systemd_failed.state.json` — the plugin's own cache file."""
    return os.path.join(os.path.expanduser("~"), ".sshmap", "plugins", CACHE_NAME)


def parse_failed(text) -> Optional[List[str]]:
    """The failed unit names of a `systemctl --failed` answer; None when it is NOT that answer.

    `--no-legend` drops the header and the footer, `--plain` drops the tree characters, so a row is
    `UNIT LOAD ACTIVE SUB DESCRIPTION` and its FIRST column is the unit name. A line whose unit
    column carries no type suffix is not a row — it is a diagnostic ("command not found", "System
    has not been booted with systemd"), and an answer like that is NO DATA: an EMPTY answer is the
    healthy host, a non-empty one with no row is never read as "nothing failed".
    """
    units: List[str] = []
    for raw in str(text or "").splitlines():
        parts = raw.split(None, 4)
        if len(parts) < 4:
            continue
        unit = parts[0].strip()
        if unit.lower().endswith(UNIT_SUFFIXES) and unit not in units:
            units.append(unit)
    if units:
        return units
    return [] if not str(text or "").strip() else None


def detail_text(count: int, units) -> str:
    """`"2 failed: nginx.service, docker.service"` — the ONE detail line of a node."""
    names = ", ".join(str(unit) for unit in list(units or [])[:MAX_UNITS])
    try:
        total = int(count)
    except (TypeError, ValueError):
        total = len(units or [])
    extra = max(0, total - len(list(units or [])[:MAX_UNITS]))
    tail = f" (+{extra} more)" if extra else ""
    if not total:
        return "no failed unit"
    return f"{total} failed: {names}{tail}" if names else f"{total} failed"


def _clean_record(record) -> Optional[dict]:
    """One stored record, validated (`None` for junk — a broken entry is dropped, not fatal)."""
    if not isinstance(record, dict):
        return None
    units = [str(unit).strip() for unit in (record.get("units") or [])
             if str(unit).strip() and str(unit).strip().lower().endswith(UNIT_SUFFIXES)]
    try:
        count = int(record.get("count"))
    except (TypeError, ValueError):
        count = len(units)
    count = max(count, len(units), 0)
    try:
        stamp = float(record.get("ts") or 0.0)
    except (TypeError, ValueError):
        stamp = 0.0
    return {"alias": str(record.get("alias") or ""), "count": count,
            "units": units[:MAX_UNITS], "ts": stamp}


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
        handle, temp_path = tempfile.mkstemp(prefix=".systemd_failed-", suffix=".tmp", dir=folder)
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
    """The COLLECTOR: `systemctl --failed` on every node the user gave us, then ONE cache write.

    The hook runs on a managed worker thread and the SSH work goes through `ctx.run_command()`,
    so the credentials, the transport, the per-node timeout and "one node's failure never stops
    the others" are the core's business. A node without a usable answer is a log line: the status
    bar counts what really answered.
    """
    records = list(nodes or [])
    if not records:
        ctx.status("systemd: nothing selected", 3000)
        return
    collected: Dict[str, dict] = {}
    failures = []

    def on_result(node, result):
        """One node's answer (or its failure) — a failure is a result for THAT node."""
        if result.error or result.exit_code != 0:
            failures.append(node.id)
            ctx.log(f"systemd: {node.label()} — no answer "
                    f"({result.error or 'exit code ' + str(result.exit_code)})")
            return
        units = parse_failed(result.output)
        if units is None:
            failures.append(node.id)
            ctx.log(f"systemd: {node.label()} — no systemd answer from `{COMMAND}`")
            return
        collected[node.id] = {"alias": node.alias, "count": len(units),
                              "units": units[:MAX_UNITS], "ts": time.time()}
        ctx.log(f"systemd: {node.label()} — {detail_text(len(units), units)}")

    def on_finished(results):
        """The whole round: one atomic cache write, then the line the user reads."""
        saved = save_cache(collected) if collected else False
        flagged = [record for record in collected.values() if record["count"]]
        ctx.status(f"systemd: {len(collected)} node(s), {len(flagged)} with a failed unit", 5000)
        if collected and not saved:
            ctx.log("systemd: the cache could not be written — the card keeps the SSH status")
        if failures:
            ctx.log(f"systemd: {len(failures)} node(s) without an answer: "
                    f"{', '.join(sorted(failures))}")

    if not ctx.run_command(records, COMMAND, on_result=on_result, on_finished=on_finished):
        ctx.log("systemd: run_command() refused the call (no nodes or an empty command)")
        ctx.status("systemd: nothing to do", 3000)


def status_probe(node):
    """The REPORTER: `("warn", "<n> failed: <unit>…")`, or None for "no opinion".

    Reads the cache and NOTHING else: this runs for EVERY node on EVERY status round, inside the
    parallel probe pool, so an SSH (or file-system) call here would hammer the servers and bypass
    the core's credential resolver. The count of ZERO is `None` on purpose — the plugin reports a
    fact it OWNS and stays silent about the rest, so it can never brighten a card the SSH probe
    marked down. A host with no systemd simply has no record (the collector refused the answer).
    """
    record = fresh_record(getattr(node, "id", ""))
    if record is None or not record["count"]:
        return None
    return ("warn", detail_text(record["count"], record["units"]))
