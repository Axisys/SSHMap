# -*- coding: utf-8 -*-
"""SSH Map example plugin — the App Version Check: the versions of nginx, Grafana, Loki, Alloy,
Prometheus, Tempo, Telegraf and Promtail, compared against a baseline file YOU own.

The shape is the disk-monitor one — the COLLECTOR and the READER are two different concerns.
`run_on_nodes(nodes, ctx)` sends ONE generated POSIX-sh probe per node through `ctx.run_command()`
(credentials, transport, per-node timeout are the CORE's); the script only COLLECTS evidence
(`R|app|path` for a running process, `V|app|state|path|flag|<first line>` for every version attempt)
and `parse_probe()` makes every decision in pure Python. The report leaves as `ctx.log()` lines — rows
of the Plugins window, which exports them to a text file — and the expected versions come from
`~/.sshmap/plugins/app_versions.baseline.json`, a data file with no code in it that you edit by hand
(`Versions: write the baseline file` in Ctrl+K seeds it from the last collection). A plugin never
imports the core (PLUGINS.md §6); the folder's rule is `examples/README.md`."""

import json
import os
import re
import tempfile
import time
from typing import Dict, List, Optional, Tuple

MANIFEST = {
    "name": "app_versions",
    "version": "1.0",
    "api_version": 1,
    "description": "Checks the versions of nginx, Grafana, Loki, Alloy, Prometheus, Tempo, "
                   "Telegraf and Promtail on the selected servers against a baseline you own",
}

PROBE_MARGIN_S = 20.0         # the probe's fixed overhead: the /proc walk, the shell, the end marker
VERSION_TIMEOUT_S = 4         # inside the probe: ONE `<binary> <flag>` attempt
MAX_FLAGS = 3                 # flag attempts per app; `_clean_app` caps a user's flag list here
DEFAULT_FLAGS = ("--version", "-version")
PROBE_MARKER = "E|end"        # the probe's own last line: proves the whole script really ran
CACHE_NAME = "app_versions.state.json"
CACHE_VERSION = 1
MAX_RECORDS = 50
BASELINE_NAME = "app_versions.baseline.json"
BASELINE_VERSION = 1

# ── the catalog: WHAT is checked and HOW it is recognised ─────────────────────────
# `names` are the BASENAMES of the running process (`/proc/<pid>/cmdline` carries the real path);
# `flags` are tried IN ORDER until one prints a version (`nginx --version` prints usage, `-v` the
# version); `paths` are where a STOPPED app is still found and `cmds` its PATH names. Every entry was
# verified against real hosts (the paths, the flags and the exact version wording).
DEFAULT_APPS: Dict[str, dict] = {
    "nginx": {"names": ["nginx"], "flags": ["-v"],
              "paths": ["/usr/sbin/nginx", "/usr/local/sbin/nginx", "/usr/local/nginx/sbin/nginx"],
              "cmds": ["nginx"]},
    "grafana": {"names": ["grafana", "grafana-server"], "flags": ["--version", "-v"],
                "paths": ["/usr/share/grafana/bin/grafana", "/usr/sbin/grafana-server",
                          "/usr/local/bin/grafana"],
                "cmds": ["grafana", "grafana-server"]},
    "prometheus": {"names": ["prometheus"], "flags": ["--version", "-version"],
                   "paths": ["/usr/local/bin/prometheus", "/opt/prometheus/prometheus",
                             "/usr/bin/prometheus"],
                   "cmds": ["prometheus"]},
    "loki": {"names": ["loki", "loki-linux-amd64", "loki-linux-arm64"],
             "flags": ["--version", "-version"],
             "paths": ["/usr/local/bin/loki", "/usr/local/bin/loki-linux-amd64",
                       "/opt/loki/loki-linux-amd64"],
             "cmds": ["loki", "loki-linux-amd64"]},
    "tempo": {"names": ["tempo", "tempo-linux-amd64"], "flags": ["--version", "-version"],
              "paths": ["/usr/local/bin/tempo", "/opt/tempo/tempo"],
              "cmds": ["tempo", "tempo-linux-amd64"]},
    "telegraf": {"names": ["telegraf"], "flags": ["-version", "--version"],
                 "paths": ["/usr/bin/telegraf", "/usr/local/bin/telegraf",
                           "/opt/wso2/telegraf/telegraf"],
                 "cmds": ["telegraf"]},
    "alloy": {"names": ["alloy", "alloy-linux-amd64", "alloy-linux-arm64"],
              "flags": ["--version", "-version"],
              "paths": ["/usr/local/bin/alloy", "/opt/wso2/alloy/alloy-linux-amd64",
                        "/usr/bin/alloy"],
              "cmds": ["alloy", "alloy-linux-amd64"]},
    "promtail": {"names": ["promtail", "promtail-linux-amd64", "promtail-linux-arm64"],
                 "flags": ["--version", "-version"],
                 "paths": ["/usr/local/bin/promtail", "/usr/local/bin/promtail-linux-amd64",
                           "/usr/bin/promtail"],
                 "cmds": ["promtail", "promtail-linux-amd64"]},
}

# ── the allowlist of everything that reaches the generated shell ──────────────────
# An app id, a path and a flag are values a FOREIGN parser acts on (AGENTS.md §4.4): the baseline
# file is a data file a user edits, so each token is checked against ONE pure predicate and a token
# that fails is DROPPED, never quoted into the script and hoped for.
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]*$")
SAFE_PATH_RE = re.compile(r"^/[A-Za-z0-9_./+-]*$")
SAFE_FLAG_RE = re.compile(r"^-{1,2}[A-Za-z0-9][A-Za-z0-9-]*$")


def _safe(value, pattern: "re.Pattern") -> str:
    """One shell-bound token: the text when it passes `pattern`, "" when it does not."""
    text = "" if value is None else str(value)
    return text if pattern.match(text) else ""


def _tokens(value, pattern: "re.Pattern", limit: int = 0) -> List[str]:
    """The allowlisted tokens of a JSON list (a broken entry costs that token, never the app)."""
    if not isinstance(value, (list, tuple)):
        return []
    out = [_safe(item, pattern) for item in value]
    out = [item for item in out if item]
    return out[:limit] if limit else out


def _clean_app(name, spec) -> Optional[dict]:
    """One catalog entry, allowlisted (`None` for junk — the entry is skipped, not fatal)."""
    app = _safe(name, SAFE_ID_RE)
    if not app or not isinstance(spec, dict):
        return None
    names = _tokens(spec.get("names"), SAFE_ID_RE)
    flags = _tokens(spec.get("flags"), SAFE_FLAG_RE, limit=MAX_FLAGS) or list(DEFAULT_FLAGS)
    paths = _tokens(spec.get("paths"), SAFE_PATH_RE)
    cmds = _tokens(spec.get("cmds"), SAFE_ID_RE)
    if not (names or paths or cmds):
        return None
    return {"names": names, "flags": flags, "paths": paths, "cmds": cmds}


# ── the plugin's own files: the cache and the baseline ─────────────────────────────

def plugin_dir() -> str:
    """`~/.sshmap/plugins` — where a folder plugin lives, and where its data lives with it."""
    return os.path.join(os.path.expanduser("~"), ".sshmap", "plugins")


def cache_path() -> str:
    """`~/.sshmap/plugins/app_versions.state.json` — what the last collection saw."""
    return os.path.join(plugin_dir(), CACHE_NAME)


def baseline_path() -> str:
    """`~/.sshmap/plugins/app_versions.baseline.json` — the expected versions (the user's file)."""
    return os.path.join(plugin_dir(), BASELINE_NAME)


def _write_json(document, path: str) -> bool:
    """Write a document ATOMICALLY (a temp file in the folder + `os.replace`); False on failure."""
    folder = os.path.dirname(path)
    temp_path = ""
    try:
        os.makedirs(folder, exist_ok=True)
        handle, temp_path = tempfile.mkstemp(prefix=".app_versions-", suffix=".tmp", dir=folder)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
        return True
    except Exception:                       # noqa: BLE001 — a data file is disposable/owned
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass
        return False


def _read_json(path: str):
    """The parsed document, or None for a missing / unreadable / foreign file. Never raises."""
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:                       # missing, unreadable, not JSON — all "no file"
        return None


def load_baseline() -> dict:
    """The baseline document (`{"expected": …, "nodes": …, "apps": …}`); `{}` when there is none.

    The file is the user's, so every key is optional and every value is validated on READ: a
    missing file means "no expectation" (the collector still reports what it FOUND), a broken one
    costs the expectation, never the run.
    """
    document = _read_json(baseline_path())
    if not isinstance(document, dict):
        return {}
    out: Dict[str, object] = {}
    expected = {}
    for app, version in (document.get("expected") or {}).items():
        if isinstance(version, str):
            expected[str(app)] = version.strip()
    out["expected"] = expected
    nodes = {}
    for key, block in (document.get("nodes") or {}).items():
        if isinstance(block, dict):
            nodes[str(key)] = {str(app): str(ver).strip() for app, ver in block.items()
                               if isinstance(ver, str)}
    out["nodes"] = nodes
    apps = {}
    for name, spec in (document.get("apps") or {}).items():
        good = _clean_app(name, spec)
        if good is not None:
            apps[str(name)] = good
    out["apps"] = apps
    return out


def catalog() -> Dict[str, dict]:
    """`DEFAULT_APPS` merged with the baseline's own `apps` (a user entry wins, per app).

    This is what makes the plugin extensible WITHOUT a code change: the probe script is generated
    from this mapping, so an app added to the baseline file is probed on the next run.
    """
    apps: Dict[str, dict] = {}
    for name, spec in DEFAULT_APPS.items():
        good = _clean_app(name, spec)
        if good is not None:
            apps[str(name)] = good
    for name, spec in (load_baseline().get("apps") or {}).items():
        good = _clean_app(name, spec)
        if good is not None:
            apps[str(name)] = good
    return apps


def probe_timeout(apps=None) -> float:
    """The per-node budget `ctx.run_command` gets — DERIVED from the LIVE catalog, never declared.

    The worst case of the generated script is one `timeout` deadline per flag attempt of every app
    (the flags are tried IN ORDER until one prints a version), plus the `/proc` walk, the shell and
    the end marker. A DECLARED number goes stale the moment the baseline file adds an app — a host
    with all of them installed would then answer "the probe did not finish" instead of a report —
    so the budget is computed from the same specs the script is generated from.
    """
    specs = apps if isinstance(apps, dict) else catalog()
    attempts = 0
    for spec in specs.values():
        if isinstance(spec, dict):
            attempts += max(1, len(spec.get("flags") or DEFAULT_FLAGS))
    return float(attempts) * VERSION_TIMEOUT_S + PROBE_MARGIN_S


# ── reading a version line (pure, no socket) ──────────────────────────────────────

VERSION_RE = re.compile(r"\d+(?:\.\d+)+")


def parse_version(text) -> str:
    """The FIRST dotted number of a version line — `"nginx version: nginx/1.30.2"` → `"1.30.2"`.

    Verified against the real wording of every shipped app: `"grafana version 13.1.1"`,
    `"prometheus, version 3.12.0 (branch: HEAD, revision: 9f27…)"`,
    `"loki, version 3.7.1 (branch: release-3.7.x, …)"`, `"tempo, version 2.0.1 (…)"`,
    `"Telegraf 1.39.3 (git: HEAD@eb37a442)"`, `"alloy, version v1.15.1 (…)"` (the `v` is not part of
    the number) — and a line with no dotted number at all (`"Usage of /usr/local/bin/loki:"`,
    the error an unknown flag prints) answers "" so the caller can try the NEXT flag.
    """
    found = VERSION_RE.search(str(text or ""))
    return found.group(0) if found else ""


def version_key(text) -> Tuple[int, ...]:
    """`"1.30.2"` / `"v1.15.1"` → `(1, 30, 2)` — the comparable form.

    NUMERIC on purpose (a string compare puts 1.9 above 1.10) and tolerant of a `v` prefix or a
    suffix (`"release-3.7.x"` never reaches here, but a user may type `v1.15.1` in the baseline).
    """
    parts = []
    for chunk in str(text or "").split("."):
        digits = ""
        for char in chunk:
            if char.isdigit():
                digits += char
            elif digits:
                break            # the number ended (`"7x"` → 7)
        if not digits:
            break                # a chunk with no digit at all ends the version (`"x"`, `""`)
        parts.append(int(digits))
    return tuple(parts)


def compare_versions(observed, expected) -> str:
    """`"ok"` / `"outdated"` / `"newer"` / `"unknown"` — the ONE comparison rule of the report."""
    seen, want = version_key(observed), version_key(expected)
    if not seen or not want:
        return "unknown"
    if seen == want:
        return "ok"
    return "outdated" if seen < want else "newer"


# ── the probe: ONE generated POSIX-sh script per node ─────────────────────────────

def build_probe_script(apps=None) -> str:
    """The ONE shell command a node runs — it COLLECTS evidence, `parse_probe()` decides.

    PURE and fully testable. The lines it prints:
      `R|<app>|<path>`                              a RUNNING process whose argv basename matched
      `V|<app>|<state>|<path>|<flag>|<first line>`  one version ATTEMPT (state running/installed)
      `V|<app>|absent|||`                           no process and no binary to ask

    Only `/proc/<pid>/cmdline` is read — world-readable, unlike `/proc/<pid>/exe`, which the kernel
    refuses for another user's process — and only **`argv[0]`** is matched, only when it is an
    ABSOLUTE path: a process really RUNS an app when it was LAUNCHED as that binary, while a shell
    whose command line merely mentions `/usr/sbin/nginx` is not nginx. That also means the script can
    never mistake ITSELF for a service, and a relative `./loki` launch falls back to the `paths`
    branch (reported as "not running", the safe direction). Every `<binary> <flag>` attempt is
    bounded by `timeout` and every flag list is short: the worst case is apps x flags x
    VERSION_TIMEOUT_S, which is exactly what `probe_timeout()` derives the node's budget from.
    """
    specs: Dict[str, dict] = {}
    for name, spec in (apps if isinstance(apps, dict) else DEFAULT_APPS).items():
        good = _clean_app(name, spec)
        if good is not None:
            specs[str(name)] = good

    lines = [
        "# sshmap app_versions — collects evidence only; the reader is pure Python on the other side.",
        'TMO=""',
        # coreutils' own path FIRST: a PATH lookup can find a foreign binary of the same name (a
        # Windows `timeout.exe` in an MSYS shell), while `/usr/bin/timeout` is the one that honours
        # `timeout <seconds> <command>`; the PATH is the fallback for a busybox-only system.
        'if [ -x /usr/bin/timeout ]; then TMO=/usr/bin/timeout',
        "elif command -v timeout >/dev/null 2>&1; then TMO=timeout; fi",
        "probe() {",
        '  if [ -n "$TMO" ]; then',
        '    line=$($TMO ' + str(VERSION_TIMEOUT_S) + ' "$3" "$4" 2>&1 | head -n1)',
        "  else",
        '    line=$("$3" "$4" 2>&1 | head -n1)',
        "  fi",
        '  if [ -n "$line" ]; then printf \'V|%s|%s|%s|%s|%s\\n\' "$1" "$2" "$3" "$4" "$line"; fi',
        "  return 0",
        "}",
    ]
    vars_by_app = {app: "p_" + re.sub(r"[^A-Za-z0-9_]", "_", app) for app in specs}
    for app in specs:
        lines.append(vars_by_app[app] + '=""')
    lines += [
        "self=$$",
        "for d in /proc/[0-9]*; do",
        '  if [ ! -r "$d/cmdline" ]; then continue; fi',
        "  pid=${d#/proc/}",
        '  if [ "$pid" = "$self" ]; then continue; fi',
        "  exe=$(tr '\\000' '\\n' < \"$d/cmdline\" 2>/dev/null | head -n1)",
        '  if [ -z "$exe" ]; then continue; fi',
        '  case "$exe" in /*) ;; *) continue ;; esac',
        '  case "${exe##*/}" in',
    ]
    for app, spec in specs.items():
        names = "|".join(spec["names"])
        var = vars_by_app[app]
        if not names:
            continue                     # no process name to match — the `paths` branch covers it
        lines.append("    " + names + ") if [ -z \"$" + var + "\" ]; then " + var
                     + "=$exe; printf 'R|" + app + "|%s\\n' \"$exe\"; fi ;;")
    lines += ["  esac", "done"]
    for app, spec in specs.items():
        var = vars_by_app[app]
        flags = " ".join(spec["flags"])
        block = ["if [ -n \"$" + var + "\" ]; then",
                 "  for f in " + flags + "; do probe " + app + " running \"$" + var + "\" \"$f\"; done",
                 "else",
                 '  x=""']
        if spec["paths"]:
            block.append("  for c in " + " ".join(spec["paths"])
                         + '; do if [ -x "$c" ]; then x=$c; break; fi; done')
        if spec["cmds"]:
            block.append('  if [ -z "$x" ]; then for n in ' + " ".join(spec["cmds"])
                         + '; do x=$(command -v "$n" 2>/dev/null); if [ -n "$x" ]; then break; fi; done; fi')
        block.append("  if [ -n \"$x\" ]; then for f in " + flags + "; do probe " + app
                     + " installed \"$x\" \"$f\"; done; else printf 'V|" + app + "|absent|||\\n'; fi")
        block.append("fi")
        lines += block
    # The LAST line is a MARKER: without it the answer was cut short (a missing `tr`, a killed
    # command, a truncated channel) and "every app absent" must never be read as "nothing installed".
    lines.append("printf '" + PROBE_MARKER + "\\n'")
    lines.append("exit 0")
    return "\n".join(lines) + "\n"


def probe_completed(text) -> bool:
    """True when the probe reached its own last line (the MARKER is in the answer)."""
    for raw in str(text or "").splitlines():
        if raw.strip() == PROBE_MARKER:
            return True
    return False


STATE_RANK = {"absent": 0, "installed": 1, "running": 2}


def parse_probe(text, apps=None) -> Dict[str, dict]:
    """Every catalog app with what the probe found — the PURE decision over the evidence lines.

    Returns `{app: {"state": "running"|"installed"|"absent", "path": str, "line": str,
    "version": str}}` for EVERY app of the catalog: an app the answer says nothing about is
    "absent", because a report has to be written from the CATALOG (what the user asked about),
    never from whatever came back.

    The kind of evidence is NOT the answer by itself: a version string wins over a missing one
    first, and a RUNNING process wins over an installed binary second — a probe whose `--version`
    printed a usage line is not allowed to hide a working `-version` attempt.
    """
    table: Dict[str, dict] = {}
    for name in (apps if isinstance(apps, dict) else DEFAULT_APPS):
        table[str(name)] = {"state": "absent", "path": "", "line": "", "version": ""}
    running: Dict[str, str] = {}
    attempts: Dict[str, List[dict]] = {}
    for raw in str(text or "").splitlines():
        fields = raw.split("|", 5)
        kind = fields[0].strip()
        app = fields[1].strip() if len(fields) > 1 else ""
        if app not in table:
            continue
        if kind == "R":
            path = fields[2].strip() if len(fields) > 2 else ""
            if path and not running.get(app):
                running[app] = path
        elif kind == "V":
            state = fields[2].strip() if len(fields) > 2 else ""
            line = fields[5].strip() if len(fields) > 5 else ""
            attempts.setdefault(app, []).append({
                "state": state if state in STATE_RANK else "installed",
                "path": fields[3].strip() if len(fields) > 3 else "",
                "line": line,
                "version": parse_version(line),
            })
    for app, options in attempts.items():
        best = max(options, key=lambda item: (1 if item["version"] else 0,
                                              STATE_RANK.get(item["state"], 1)))
        table[app] = {"state": best["state"], "path": best["path"], "line": best["line"],
                      "version": best["version"]}
    for app, path in running.items():
        if table[app]["state"] == "absent":
            table[app] = {"state": "running", "path": path, "line": "", "version": ""}
    return table


# ── the report (pure: the test seam of the whole plugin) ──────────────────────────

def _field(node, name, default=""):
    """One field of a node-like value: a `PluginNode`, or the plain dict the Ctrl+K door passes back.

    `PluginContext.run_command()` accepts anything node-like, so the two shapes reach this module —
    reading both here is what keeps a cached record from being blanked on the way through.
    """
    value = node.get(name, default) if isinstance(node, dict) else getattr(node, name, default)
    return default if value is None else value


def _label(node) -> str:
    """The node's name in a report line: the record's own `label()`, else the alias / host / id."""
    fn = getattr(node, "label", None)
    if callable(fn):
        try:
            text = str(fn() or "")
        except Exception:  # noqa: BLE001 — a broken record is "no name", not a crash
            text = ""
        if text:
            return text
    alias = str(_field(node, "alias") or "")
    host = str(_field(node, "host") or "")
    return alias or host or str(_field(node, "id") or "?")


def expected_versions(node, baseline) -> Dict[str, str]:
    """The expected version per app for ONE node — the per-node block WINS over the global map.

    A fleet is not uniform (`nodes` of the baseline file exists for exactly that): the block of the
    node's ALIAS and the one of its ID are both read, the ID last, so a rename cannot lose the rule
    and an id-keyed entry cannot be shadowed by a stale alias.
    """
    expected = dict((baseline or {}).get("expected") or {})
    overrides = (baseline or {}).get("nodes") or {}
    for key in (_field(node, "alias"), _field(node, "id")):
        block = overrides.get(str(key)) if key else None
        if isinstance(block, dict):
            expected.update(block)
    return expected


def build_report(node, found, baseline) -> dict:
    """The report of ONE node — PURE, in English, one line per app plus one summary.

    Returns `{"lines": [...], "drift": int, "found": int, "missing": [...]}`. `drift` counts what a
    user may have to ACT on — an app older or newer than the baseline, and one whose version could
    not be read — while `no baseline` is a configuration state, not a defect (before the baseline is
    written every app is in it, and a status line must not cry wolf for that).

    The wording of a line is deliberately greppable — the Plugins window exports these lines to a
    text file, and the state of an app that is not RUNNING rides in the same bracket:
        `plgclient: nginx [ok] 1.30.2 (/usr/sbin/nginx)`
        `testplg: loki [outdated] 3.7.0 -> 3.7.1 (/usr/local/bin/loki-linux-amd64)`
        `testplg: alloy [ok, not running] 1.15.1 (/opt/wso2/alloy/alloy-linux-amd64)`
    """
    label = _label(node)
    expected = expected_versions(node, baseline)
    counts = {"ok": 0, "outdated": 0, "newer": 0, "no baseline": 0, "version not detected": 0}
    missing: List[str] = []
    lines: List[str] = []
    for app, entry in (found or {}).items():
        state = str(entry.get("state") or "absent")
        path = str(entry.get("path") or "")
        version = str(entry.get("version") or "")
        want = str(expected.get(app) or "")
        if state == "absent" and not version:
            missing.append(app)
            continue
        if not version:
            counts["version not detected"] += 1
            tags = ["version not detected"]
        elif not want:
            counts["no baseline"] += 1
            tags = ["no baseline"]
        else:
            verdict = compare_versions(version, want)
            if verdict == "unknown":       # a baseline value with no number in it
                counts["no baseline"] += 1
                tags = ["no baseline"]
            else:
                counts[verdict] += 1
                tags = [verdict]
        if state != "running":
            tags.append("not running")
        parts = [label + ": " + app, "[" + ", ".join(tags) + "]"]
        if version:
            if tags[0] == "outdated":
                parts.append(version + " -> " + want)
            elif tags[0] == "newer":
                parts.append(version + " > " + want)
            else:
                parts.append(version)
        if path:
            parts.append("(" + path + ")")
        lines.append(" ".join(parts))
    found_count = sum(1 for entry in (found or {}).values()
                      if not (str(entry.get("state")) == "absent" and not entry.get("version")))
    summary = label + f": {found_count}/{len(found or {})} found"
    detail = ", ".join(f"{name} {count}" for name, count in counts.items() if count)
    if detail:
        summary += " - " + detail
    if missing:
        summary += "; missing: " + ", ".join(sorted(missing))
    lines.append(summary)
    drift = counts["outdated"] + counts["newer"] + counts["version not detected"]
    return {"lines": lines, "drift": drift, "found": found_count, "missing": missing}


# ── the cache: what the last collection saw (also the seed of the baseline) ───────

def _clean_entry(entry) -> Optional[dict]:
    """One stored app entry, validated (`None` for junk — a broken entry is dropped, not fatal)."""
    if not isinstance(entry, dict):
        return None
    state = str(entry.get("state") or "")
    return {"state": state if state in STATE_RANK else "absent",
            "path": str(entry.get("path") or "")[:200],
            "line": str(entry.get("line") or "")[:200],
            "version": str(entry.get("version") or "")[:40]}


def _clean_record(record) -> Optional[dict]:
    """One stored node record, validated (`None` for junk)."""
    if not isinstance(record, dict):
        return None
    node = record.get("node")
    facts = {}
    if isinstance(node, dict) and str(node.get("id") or ""):
        try:
            port = int(node.get("port") or 22)
        except (TypeError, ValueError):
            port = 22
        facts = {"id": str(node.get("id")), "alias": str(node.get("alias") or ""),
                 "host": str(node.get("host") or ""), "port": max(1, min(65535, port)),
                 "user": str(node.get("user") or "")}
    apps = {}
    for app, entry in (record.get("apps") or {}).items():
        good = _clean_entry(entry)
        if good is not None:
            apps[str(app)] = good
    try:
        stamp = float(record.get("ts") or 0.0)
    except (TypeError, ValueError):
        stamp = 0.0
    return {"alias": str(record.get("alias") or ""), "node": facts, "apps": apps, "ts": stamp}


def load_cache() -> Dict[str, dict]:
    """The stored records keyed by node id — `{}` for a missing / broken / foreign cache."""
    document = _read_json(cache_path())
    if not isinstance(document, dict) or not isinstance(document.get("records"), dict):
        return {}
    clean: Dict[str, dict] = {}
    for node_id, record in document["records"].items():
        good = _clean_record(record)
        if good is not None:
            clean[str(node_id)] = good
    return clean


def save_cache(records) -> bool:
    """Merge + prune + write the cache ATOMICALLY (False on failure — a lost cache costs nothing).

    The merge is what makes a per-node collection cheap: a node that was not part of this round
    keeps its previous answer, and the file (not the process) is what `known_nodes()` reads.
    """
    if not isinstance(records, dict):
        return False
    merged = load_cache()
    for node_id, record in records.items():
        good = _clean_record(record)
        if good is not None:
            merged[str(node_id)] = good
    ordered = sorted(merged.items(), key=lambda item: float(item[1].get("ts") or 0.0), reverse=True)
    document = {"version": CACHE_VERSION, "records": dict(ordered[:MAX_RECORDS])}
    return _write_json(document, cache_path())


def known_nodes() -> List[dict]:
    """The node records of the last collections, newest first (the Ctrl+K re-check target)."""
    out = []
    for _node_id, record in sorted(load_cache().items(),
                                   key=lambda item: float(item[1].get("ts") or 0.0), reverse=True):
        facts = record.get("node") or {}
        if facts.get("id"):
            out.append(dict(facts))
    return out


def baseline_template(cache=None) -> dict:
    """The starter baseline: `expected` seeded with the NEWEST version last seen, per app.

    A seed, not a decision: the file exists so the versions can be corrected by hand — which is
    why `expected` is filled from the cache and `nodes` / `apps` stay empty examples.
    """
    seen: Dict[str, List[str]] = {}
    for record in (cache or load_cache()).values():
        for app, entry in (record.get("apps") or {}).items():
            version = str(entry.get("version") or "")
            if version:
                seen.setdefault(app, []).append(version)
    expected = {}
    for app in catalog():
        versions = seen.get(app) or []
        expected[app] = max(versions, key=version_key) if versions else ""
    return {
        "version": BASELINE_VERSION,
        "_comment": ("expected = the version you want on EVERY server; nodes[<alias or node id>] "
                     "overrides it for one server; apps adds an app this plugin does not ship "
                     "(names / flags / paths / cmds). An empty string means \"no opinion\"."),
        "expected": expected,
        "nodes": {},
        "apps": {},
    }


# ── the hooks ─────────────────────────────────────────────────────────────────────

def _short(text, limit: int = 200) -> str:
    """One-line, length-capped text (an error travels to a tooltip and a log line)."""
    flat = " ".join(str(text or "").split())
    return flat[:limit] + "..." if len(flat) > limit else flat


def _node_facts(node) -> dict:
    """The plugin-visible record of a node, kept so a later re-check can reach it again (no secret)."""
    try:
        port = int(_field(node, "port", 22) or 22)
    except (TypeError, ValueError):
        port = 22
    return {"id": str(_field(node, "id") or ""), "alias": str(_field(node, "alias") or ""),
            "host": str(_field(node, "host") or ""), "port": max(1, min(65535, port)),
            "user": str(_field(node, "user") or "")}


def collect(records, ctx) -> bool:
    """The COLLECTOR both doors call: ONE generated probe per node, the report as `ctx.log()` lines.

    Every app line is the plugin's own text, so the Plugins window shows it VERBATIM and exports it
    to a text file. A node whose probe did not answer is a failure for THAT node and never stops the
    others (the runner's own rule); the exit code is the truth, so a command that wrote to stderr and
    exited 0 is not called a failure.
    """
    nodes = list(records or [])
    if not nodes:
        ctx.status("versions: nothing selected", 3000)
        return False
    apps = catalog()
    baseline = load_baseline()
    script = build_probe_script(apps)
    collected: Dict[str, dict] = {}
    failures: List[str] = []
    state = {"drift": 0}

    def on_result(node, result):
        """One node's answer (or its failure) — a failure is a result for THAT node."""
        node_id = str(_field(node, "id") or "")
        if result.exit_code != 0 or not str(result.output or "").strip():
            failures.append(node_id)
            ctx.log(f"versions: {_label(node)} - no answer "
                    f"({_short(result.error) or 'exit code ' + str(result.exit_code)})")
            return
        if not probe_completed(result.output):
            failures.append(node_id)
            ctx.log(f"versions: {_label(node)} - the probe did not finish "
                    f"({_short(result.error) or 'no end marker in the answer'})")
            return
        found = parse_probe(result.output, apps)
        collected[node_id] = {"alias": str(_field(node, "alias") or ""), "node": _node_facts(node),
                              "apps": found, "ts": time.time()}
        report = build_report(node, found, baseline)
        for line in report["lines"]:
            ctx.log(line)
        if report["drift"]:
            state["drift"] += 1

    def on_finished(results):
        """The whole round: one atomic cache write, then the line the user reads."""
        saved = save_cache(collected) if collected else False
        ctx.status(f"versions: {len(collected)} node(s), {state['drift']} to look at", 8000)
        if collected and not saved:
            ctx.log("versions: the cache could not be written - the report above still stands")
        if failures:
            ctx.log(f"versions: {len(failures)} node(s) without an answer: {', '.join(sorted(failures))}")

    if not ctx.run_command(nodes, script, on_result=on_result, on_finished=on_finished,
                           timeout=probe_timeout(apps)):
        ctx.log("versions: run_command() refused the call (no nodes or an empty command)")
        ctx.status("versions: nothing to do", 3000)
        return False
    return True


def run_on_nodes(nodes, ctx):
    """The hook of "Run on selected servers" (and of the Plugins window's per-row run).

    The hook runs on a managed worker thread (PLUGINS.md §6) and returns immediately: the SSH work
    is `ctx.run_command()`, whose per-node callbacks arrive on the GUI thread, so the report is
    written while the run is already asynchronous and the application stays responsive.
    """
    collect(nodes, ctx)


def register_commands(ctx):
    """Ctrl+K: a re-check of every known server, and the baseline template.

    Returned as plain `(text, callback)` pairs — the lenient shape of PLUGINS.md §3 — which keeps
    this file free of any import of the core. Neither callback does IO: the first only reads the
    plugin's own cache file and starts the ordinary run, the second writes ONE small JSON file.
    """
    return [("Versions: re-check every known server", _recheck_known),
            ("Versions: write the baseline file", _write_baseline)]


def _recheck_known(ctx):
    """Ctrl+K: re-run the probe on every server the last collections know about.

    A palette command has no access to the map's SELECTION (PLUGINS.md §5 hands a plugin no scene),
    so this is the "same fleet as last time" door; the selection-driven run stays the Plugins window.
    """
    records = known_nodes()
    if not records:
        ctx.status("versions: no server is known yet - run it from the Plugins window first", 6000)
        return
    ctx.log(f"versions: re-checking {len(records)} known server(s)")
    collect(records, ctx)


def _write_baseline(ctx):
    """Ctrl+K: write the baseline TEMPLATE — an EXISTING file is never overwritten (it is yours)."""
    path = baseline_path()
    if os.path.exists(path):
        ctx.status("versions: the baseline file already exists - edit it by hand", 6000)
        ctx.log(f"versions: baseline kept: {path}")
        return
    try:
        count = len(catalog())
        document = baseline_template()
        if _write_json(document, path):
            ctx.status("versions: baseline written - edit the expected versions in it", 10000)
            ctx.log(f"versions: baseline written with {count} app(s): {path}")
        else:
            ctx.status("versions: the baseline file could not be written", 6000)
            ctx.log(f"versions: could not write {path} - check the folder permissions")
    except Exception as exc:  # noqa: BLE001 — a command must never raise into the host
        ctx.log(f"versions: the baseline template failed: {type(exc).__name__}: {exc}")
