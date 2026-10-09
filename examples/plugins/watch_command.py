# -*- coding: utf-8 -*-
"""SSH Map example plugin — the Watch Command (the user's own fact, the plugin's own settings).

This file is an EXAMPLE, not a shipped plugin (see `examples/README.md`): copy it into
`~/.sshmap/plugins/` and use "Plugins → Reload". It answers the v1 question "where do a plugin's
settings live?" — in ITS own file (`watch_command.json`) beside its cache, merge-on-write, because
API v1 registers no settings section and the parity policy is not the plugin's (`PLUGINS.md` §7).

The config maps a node (by ID or by host) to a command, the regex that means "warn" and the detail
to show; `run_on_nodes(nodes, ctx)` collects it and `status_probe(node)` reports it from the cache.
The command runs VERBATIM as the user wrote it — the plugin interpolates NOTHING into it (where
`app_versions.py` teaches the other side of the same boundary: a hostile app name is DROPPED). A
plugin sees no tags and no notes, so this config is its ONLY way to say "these nodes, not those"."""

import json
import os
import re
import tempfile
import time
from typing import Dict, List, Optional, Tuple

MANIFEST = {
    "name": "watch_command",
    "version": "1.0",
    "api_version": 1,
    "description": "Runs a command of your own per server and warns when its output matches your regex",
}

CONFIG_NAME = "watch_command.json"
CACHE_NAME = "watch_command.state.json"
CACHE_VERSION = 1
STALE_SECONDS = 3600
MAX_RECORDS = 50
MAX_COMMAND_CHARS = 500
MAX_PATTERN_CHARS = 200
MAX_DETAIL_CHARS = 120
MAX_OUTPUT_CHARS = 20000        # the regex searches a bounded answer, never a whole 1 MB capture
DETAIL_FALLBACK = "the watch command matched"
TEMPLATE = {"default": {"command": "", "warn_pattern": "", "detail": ""}, "nodes": {}}


# ── the plugin's own settings ─────────────────────────────────────────────────────
# `{"default": <entry>, "nodes": {"<node id or host>": <entry>}}`, and an entry is
# `{"command": …, "warn_pattern": …, "detail": …}`. Both a command and a pattern are
# REQUIRED: an entry without them is dropped on read, so a typo in the file can never
# make the plugin warn about nothing (or ask a server to run an empty line).

def config_path() -> str:
    """`~/.sshmap/plugins/watch_command.json` — the plugin's own settings file."""
    return os.path.join(os.path.expanduser("~"), ".sshmap", "plugins", CONFIG_NAME)


def compiled(pattern) -> Optional[re.Pattern]:
    """The user's regex, or None when it is unusable (a typo never raises into a probe)."""
    text = str(pattern or "")
    if not text or len(text) > MAX_PATTERN_CHARS:
        return None
    try:
        return re.compile(text)
    except re.error:
        return None


def _clean_entry(raw) -> Optional[dict]:
    """One config entry, validated (`None` for junk — a broken entry is dropped, not fatal)."""
    if not isinstance(raw, dict):
        return None
    command = str(raw.get("command") or "").strip()
    pattern = str(raw.get("warn_pattern") or "").strip()
    if not command or len(command) > MAX_COMMAND_CHARS:
        return None
    if compiled(pattern) is None:
        return None
    return {"command": command, "warn_pattern": pattern,
            "detail": str(raw.get("detail") or "").strip()[:MAX_DETAIL_CHARS]}


def load_config() -> dict:
    """The stored settings, validated: `{"default": <entry or None>, "nodes": {<key>: <entry>}}`."""
    try:
        with open(config_path(), encoding="utf-8") as handle:
            document = json.load(handle)
    except Exception:                       # missing, unreadable, not JSON — all "no settings"
        return {"default": None, "nodes": {}}
    if not isinstance(document, dict):
        return {"default": None, "nodes": {}}
    nodes = {}
    for key, value in (document.get("nodes") or {}).items():
        good = _clean_entry(value)
        if str(key).strip() and good is not None:
            nodes[str(key).strip()] = good
    return {"default": _clean_entry(document.get("default")), "nodes": nodes}


def entry_for(node, config=None) -> Optional[dict]:
    """The entry of ONE node: its own (by ID, then by host), else the default — None when neither."""
    settings = load_config() if config is None else config
    for key in (str(getattr(node, "id", "") or "").strip(),
                str(getattr(node, "host", "") or "").strip()):
        if key and key in settings["nodes"]:
            return settings["nodes"][key]
    return settings["default"]


def group_by_command(nodes, config=None) -> Tuple[List[Tuple[str, list]], List[str]]:
    """The run PLAN: `[(command, [(node, entry), …]), …]` plus the ids that have no entry.

    ONE `ctx.run_command()` per DISTINCT command, because that call opens its own connection per
    node per call: a fleet watching one fact costs one connection per node, not one per node per
    entry, and the nodes are grouped instead of asking each of them twice.
    """
    settings = load_config() if config is None else config
    groups: Dict[str, list] = {}
    skipped: List[str] = []
    for node in list(nodes or []):
        entry = entry_for(node, settings)
        if entry is None:
            skipped.append(str(getattr(node, "id", "") or ""))
            continue
        groups.setdefault(entry["command"], []).append((node, entry))
    return list(groups.items()), skipped


def first_matching_line(output, pattern) -> str:
    """The first line of the answer the pattern matched (the detail a user did not write)."""
    rx = pattern if hasattr(pattern, "search") else compiled(pattern)
    if rx is None:
        return ""
    for raw in str(output or "")[:MAX_OUTPUT_CHARS].splitlines():
        if rx.search(raw):
            return raw.strip()[:MAX_DETAIL_CHARS]
    return ""


def evaluate(entry, output) -> Optional[str]:
    """The detail when the entry's pattern MATCHES the answer, else None ("no match")."""
    if not entry:
        return None
    text = str(output or "")[:MAX_OUTPUT_CHARS]
    rx = compiled(entry["warn_pattern"])
    if rx is None or rx.search(text) is None:
        return None
    detail = entry["detail"] or first_matching_line(text, rx)
    return (detail or DETAIL_FALLBACK)[:MAX_DETAIL_CHARS]


# ── the cache: the plugin's own data, next to the plugin folder ───────────────────

def cache_path() -> str:
    """`~/.sshmap/plugins/watch_command.state.json` — the plugin's own cache file."""
    return os.path.join(os.path.expanduser("~"), ".sshmap", "plugins", CACHE_NAME)


def _clean_record(record) -> Optional[dict]:
    """One stored record, validated (`None` for junk — a broken entry is dropped, not fatal)."""
    if not isinstance(record, dict):
        return None
    try:
        stamp = float(record.get("ts") or 0.0)
    except (TypeError, ValueError):
        stamp = 0.0
    return {"alias": str(record.get("alias") or ""),
            "command": str(record.get("command") or "")[:MAX_COMMAND_CHARS],
            "matched": bool(record.get("matched")),
            "detail": str(record.get("detail") or "")[:MAX_DETAIL_CHARS], "ts": stamp}


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
    """Merge + prune + write the cache ATOMICALLY (a temp file in the folder + `os.replace`)."""
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
        handle, temp_path = tempfile.mkstemp(prefix=".watch_command-", suffix=".tmp", dir=folder)
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


# ── the palette door: the settings file, seeded once ──────────────────────────────

def write_template(ctx) -> bool:
    """Seed `watch_command.json` — an EXISTING file is the user's own and is never overwritten.

    The template is deliberately INERT: its `default` entry carries an empty command, which
    `_clean_entry()` refuses, and its `nodes` map is empty. A palette callback receives the
    context but no servers, so the plugin cannot fill in a node id for the user — the file is
    the user's to write, and this door only shows the shape of it.
    """
    path = config_path()
    if os.path.exists(path):
        ctx.status(f"watch: {CONFIG_NAME} already exists", 4000)
        return False
    folder = os.path.dirname(path)
    temp_path = ""
    try:
        os.makedirs(folder, exist_ok=True)
        handle, temp_path = tempfile.mkstemp(prefix=".watch_command-", suffix=".tmp", dir=folder)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(TEMPLATE, stream, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
    except Exception:                       # noqa: BLE001 — a failed seed is a status line
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass
        ctx.status("watch: the template could not be written", 4000)
        return False
    ctx.status(f"watch: template written to {path}", 5000)
    return True


def register_commands(ctx):
    """Ctrl+K: the one row that answers "where do I write the settings?"."""
    return [("Watch: write the config template", write_template)]


# ── the hooks ─────────────────────────────────────────────────────────────────────

def finish_round(ctx, collected, failures, skipped) -> None:
    """The end of a run: ONE cache write, then the line the user reads."""
    saved = save_cache(collected) if collected else False
    matched = [record for record in collected.values() if record["matched"]]
    ctx.status(f"watch: {len(collected)} node(s), {len(matched)} matching", 5000)
    if collected and not saved:
        ctx.log("watch: the cache could not be written — the card keeps the SSH status")
    if skipped:
        ctx.log(f"watch: {len(skipped)} node(s) have no entry: {', '.join(sorted(skipped))}")
    if failures:
        ctx.log(f"watch: {len(failures)} node(s) without an answer: {', '.join(sorted(failures))}")


def run_on_nodes(nodes, ctx):
    """The COLLECTOR: every node's OWN command, VERBATIM, ONE call per distinct command."""
    records = list(nodes or [])
    if not records:
        ctx.status("watch: nothing selected", 3000)
        return
    groups, skipped = group_by_command(records)
    if not groups:
        ctx.log(f"watch: no node of this run has an entry in {config_path()}")
        ctx.status("watch: nothing configured", 4000)
        return
    collected: Dict[str, dict] = {}
    failures: List[str] = []
    pending = {"left": len(groups)}

    def run_group(command, pairs):
        entries = {str(node.id): entry for node, entry in pairs}

        def on_result(node, result):
            """One node's answer (or its failure) — a failure is a result for THAT node."""
            if result.error or result.exit_code != 0:
                failures.append(node.id)
                ctx.log(f"watch: {node.label()} — no answer "
                        f"({result.error or 'exit code ' + str(result.exit_code)})")
                return
            detail = evaluate(entries.get(str(node.id)), result.output)
            collected[node.id] = {"alias": node.alias, "command": command,
                                  "matched": bool(detail), "detail": detail or "",
                                  "ts": time.time()}
            ctx.log(f"watch: {node.label()} — {detail or 'no match'}")

        def on_finished(results):
            settled()

        if not ctx.run_command([node for node, _entry in pairs], command,
                               on_result=on_result, on_finished=on_finished):
            ctx.log(f"watch: run_command() refused the call for `{command}`")
            settled()

    def settled():
        """ONE round, many calls: the summary lands when the LAST group answered."""
        pending["left"] -= 1
        if pending["left"] <= 0:
            finish_round(ctx, collected, failures, skipped)

    for command, pairs in groups:
        run_group(command, pairs)


def status_probe(node):
    """The REPORTER: `("warn", "<the detail>")` while the watch matched, else None.

    Reads the cache and NOTHING else — the command ran on the collector's managed worker with the
    core's credentials, and a probe runs for every node on every status round. A node that did not
    match, has no record or left the map is "no opinion": the plugin adds a WARNING, never a
    reassurance of its own.
    """
    record = fresh_record(getattr(node, "id", ""))
    if record is None or not record["matched"]:
        return None
    return ("warn", record["detail"] or DETAIL_FALLBACK)
