# -*- coding: utf-8 -*-
"""SSH Config Importer — bulk import of servers from an OpenSSH client config (v1.4.1).

The file `~/.ssh/config` already describes the topology of most SSH users:
one `Host` block per machine with the real host name, the login, the port and
the key. This module reads it the way `ssh` itself does and turns the blocks
into `SshConfigHost` records — the caller (`MainWindow._import_servers_from_ssh_config`)
maps them onto `ServerData` and adds them to the map as ONE undoable batch
(the v0.9.5.5 import-from-TXT pattern).

WHAT IS IMPORTED (one map node per concrete `Host` pattern)
    ``HostName``      → ``host`` (unset → the alias itself, the ssh default)
    ``User``          → ``user`` (unset → the LOCAL user name, the ssh default)
    ``Port``          → ``ssh_port`` (unset → 22; a malformed value is ignored)
    ``IdentityFile``  → ``key_path`` (the FIRST one wins; ``none`` clears it)
    ``Include``       → read RECURSIVELY at the point of the directive (see below)

WHAT IS NOT IMPORTED — and is REPORTED (the ``skipped`` / ``notes`` lists)
    * a wildcard pattern (``Host *``, ``?.example.com``) — pattern matching is
      connection-time logic, not import logic, so the block is skipped WITH its
      options: a ``Host *`` block that carries the global ``User`` is NOT applied
      to the other hosts (the one deliberate fidelity gap of the version);
    * a ``Match`` block and every directive inside it;
    * ``ProxyJump`` / ``ProxyCommand`` / ``Jump`` — the app has no jump-host
      concept; the host IS imported, the directive is dropped (a note);
    * a second ``IdentityFile`` of the same host (a note);
    * an ``Include`` that cannot be read / matches no file (a skip record — the
      rest of the config still imports).

OPENSSH RULES IMPLEMENTED
    * a directive keyword is case-INSENSITIVE;
    * the value is separated from the keyword by whitespace or ``=``;
    * ``"…"`` quoting and a trailing ``\\`` line continuation are honoured;
    * an unquoted ``#`` starts a comment and runs to the end of the line;
    * ``Host a b c`` opens a block for THREE aliases at once;
    * a pattern starting with ``!`` is an exclusion, not a host (ignored);
    * FIRST OBTAINED VALUE WINS per option: a later ``Host <same alias>`` block
      does not override an option already set, it only fills the gaps;
    * ``Include`` paths resolve relative to ``~/.ssh`` (a glob is expanded).

DELIBERATELY OUT OF SCOPE (documented, not hidden): the default identity files
(``~/.ssh/id_rsa`` and friends) when ``IdentityFile`` is absent, per-host
``StrictHostKeyChecking``/forwarding/``known_hosts`` directives (irrelevant to a
map), a host block that STARTS in one file and CONTINUES in an included one,
and any pattern matching at connection time.

The module is HEADLESS: no Qt, no i18n, no network. Every user-visible string is
a reason CODE (``REASON_*`` / ``NOTE_*``) plus a ``detail``; the dialog owns the
translation (`dialogs/ssh_config_import_dialog.py`).

v1.5.2 (ROADMAP task 2): the loader logged nothing — an import that found no host, or
that could not read the file at all, left no trace. `load_ssh_config()` now writes ONE
record per call (the result summary, or the reason the entry file was unusable), which
reaches `sshmap.log` AND the activity panel. The parser stays silent: it runs once per
included FILE and would flood the history with intermediate lines — the loader is the
ONE place that knows the whole answer.
"""

import getpass
import glob
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

try:  # v1.5.2: the import record of the activity history (ROADMAP task 2)
    from modules.logger import get_logger
except ImportError:  # pragma: no cover — the package layout (sshmap.services.*)
    from ..modules.logger import get_logger

log = get_logger(__name__)

DEFAULT_CONFIG_RELPATH = os.path.join(".ssh", "config")
SSH_DIR_NAME = ".ssh"
MAX_INCLUDE_DEPTH = 8          # an Include chain deeper than this is not followed
DEFAULT_PORT = 22

# ── skip reasons: the host (or the block) is NOT imported ────────────────────
REASON_WILDCARD = "wildcard"            # Host * / ?.example.com — its options do not apply
REASON_MATCH = "match"                  # a Match block with everything inside it
REASON_INCLUDE_MISSING = "include_missing"   # an Include that cannot be read
REASON_DUPLICATE = "duplicate"          # the caller's deduplication (already on the map)

# ── notes: the host IS imported, one of its directives was dropped ───────────
NOTE_PROXY = "proxy"                    # ProxyJump / ProxyCommand / Jump
NOTE_IDENTITY_EXTRA = "identity_extra"  # a second IdentityFile of the same host

# ── loader error codes (the ENTRY file only; a broken Include is a skip record)
ERROR_MISSING = "missing"
ERROR_UNREADABLE = "unreadable"

WILDCARD_CHARS = "*?["
PROXY_DIRECTIVES = frozenset({"proxyjump", "proxycommand", "jump"})
_KNOWN_OPTIONS = frozenset({"hostname", "user", "port", "identityfile"})


class SshConfigError(Exception):
    """The ENTRY config file cannot be used (``code`` = ERROR_MISSING / ERROR_UNREADABLE)."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class SshConfigHost:
    """One concrete `Host` pattern, ready to become a map node."""

    alias: str
    host: str
    user: str
    port: int = DEFAULT_PORT
    key_path: str = ""
    source: str = ""      # the config file the alias was first seen in
    line: int = 0         # …and the line number of its `Host` directive


@dataclass(frozen=True)
class SshConfigIssue:
    """Something the user must be told about: a reason code + a ``detail`` string.

    ``subject`` — the alias (a note) or the pattern/directive (a skip);
    ``reason``  — one of REASON_* / NOTE_*; the dialog translates it.
    """

    subject: str
    reason: str
    detail: str = ""
    source: str = ""
    line: int = 0


@dataclass(frozen=True)
class SshConfigResult:
    """The parse/load result: hosts, the two report lists and the files actually read."""

    hosts: Tuple[SshConfigHost, ...] = ()
    skipped: Tuple[SshConfigIssue, ...] = ()
    notes: Tuple[SshConfigIssue, ...] = ()
    files: Tuple[str, ...] = ()
    path: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# Paths and token expansion
# ══════════════════════════════════════════════════════════════════════════════

def default_config_path(home: Optional[str] = None) -> str:
    """`~/.ssh/config` — the OpenSSH user config (``home`` is injectable for tests)."""
    return os.path.join(home or os.path.expanduser("~"), DEFAULT_CONFIG_RELPATH)


def expand_path_tokens(value: str, host: str = "", user: str = "",
                       home: str = "", local_user: str = "") -> str:
    """Expand the OpenSSH tokens of a path.

    ``~``/``%d`` = the local home, ``%u`` = the local user, ``%h`` = the block's
    host, ``%r`` = the block's user, ``%%`` = a literal ``%``. An unknown ``%x``
    is left as written. A relative path is returned unchanged.
    """
    home = home or os.path.expanduser("~")
    sentinel = "\x00"
    out = str(value).replace("%%", sentinel)
    out = (out.replace("%d", home)
              .replace("%u", local_user or "")
              .replace("%h", host or "")
              .replace("%r", user or ""))
    out = out.replace(sentinel, "%")
    if out.startswith("~"):
        rest = out[1:].lstrip("/\\")
        out = os.path.normpath(os.path.join(home, rest)) if rest else home
    return out


# ══════════════════════════════════════════════════════════════════════════════
# Line-level helpers (comments, continuations, quoting)
# ══════════════════════════════════════════════════════════════════════════════

def _strip_comment(line: str) -> str:
    """Drop an unquoted ``#`` and everything after it."""
    in_quote = False
    for i, ch in enumerate(line):
        if ch == '"':
            in_quote = not in_quote
        elif ch == "#" and not in_quote:
            return line[:i]
    return line


def _continues(line: str) -> bool:
    """A line ending with an ODD number of backslashes continues on the next one."""
    stripped = line.rstrip()
    return (len(stripped) - len(stripped.rstrip("\\"))) % 2 == 1


def _logical_lines(text: str):
    """Yield ``(line_number, line)``: continuations joined, comments stripped.

    The line number is the FIRST physical line of a logical line — what the
    user sees when the record is reported.
    """
    physical = text.splitlines()
    i = 0
    while i < len(physical):
        number = i + 1
        line = physical[i]
        i += 1
        while _continues(line) and i < len(physical):
            line = line.rstrip()[:-1] + " " + physical[i]
            i += 1
        yield number, _strip_comment(line)


def _split_directive(line: str) -> Tuple[Optional[str], str]:
    """``"HostName=web-1"`` → ``("hostname", "web-1")``; a blank line → ``(None, "")``."""
    s = line.strip()
    if not s:
        return None, ""
    cut = len(s)
    for i, ch in enumerate(s):
        if ch.isspace() or ch == "=":
            cut = i
            break
    key = s[:cut]
    rest = s[cut:].lstrip()
    if rest.startswith("="):
        rest = rest[1:].lstrip()
    return key.lower(), rest


def _split_values(rest: str) -> List[str]:
    """Whitespace-separated values, honouring ``"…"`` quoting."""
    values, buf, in_quote = [], [], False
    for ch in rest:
        if ch == '"':
            in_quote = not in_quote
            continue
        if ch.isspace() and not in_quote:
            if buf:
                values.append("".join(buf))
                buf = []
            continue
        buf.append(ch)
    if buf:
        values.append("".join(buf))
    return values


def _unquote(value: str) -> str:
    """The whole value with a surrounding pair of quotes removed."""
    value = value.strip()
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value


# ══════════════════════════════════════════════════════════════════════════════
# The parser
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class _Context:
    """One parse run: the injectable environment + the cycle guard."""

    home: str
    local_user: str
    visited: set = field(default_factory=set)


@dataclass
class _State:
    """The accumulator: per-alias options in first-seen order + the report lists."""

    options: Dict[str, dict] = field(default_factory=dict)
    order: List[str] = field(default_factory=list)
    source_of: Dict[str, str] = field(default_factory=dict)
    line_of: Dict[str, int] = field(default_factory=dict)
    skipped: List[SshConfigIssue] = field(default_factory=list)
    notes: List[SshConfigIssue] = field(default_factory=list)
    files: List[str] = field(default_factory=list)

    def touch(self, alias: str, source: str, line: int):
        """Register an alias in first-seen order (an existing one keeps its place)."""
        if alias not in self.options:
            self.options[alias] = {}
            self.order.append(alias)
            self.source_of[alias] = source
            self.line_of[alias] = line


def _resolve_include(pattern: str, ctx: _Context) -> str:
    """An Include path: tokens expanded; a relative one resolves against ``~/.ssh``."""
    expanded = expand_path_tokens(pattern, home=ctx.home, local_user=ctx.local_user)
    if not os.path.isabs(expanded):
        expanded = os.path.join(ctx.home, SSH_DIR_NAME, expanded)
    return os.path.normpath(expanded)


def _handle_include(rest: str, source: str, state: _State, ctx: _Context,
                    depth: int, line: int):
    """Read the included file(s) at the point of the directive (simple recursion)."""
    for pattern in _split_values(rest):
        if depth >= MAX_INCLUDE_DEPTH:
            state.skipped.append(SshConfigIssue(pattern, REASON_INCLUDE_MISSING,
                                                pattern, source, line))
            continue
        matches = [p for p in sorted(glob.glob(_resolve_include(pattern, ctx)))
                   if os.path.isfile(p)]
        if not matches:
            state.skipped.append(SshConfigIssue(pattern, REASON_INCLUDE_MISSING,
                                                pattern, source, line))
            continue
        for include_path in matches:
            real = os.path.normcase(os.path.abspath(include_path))
            if real in ctx.visited:
                continue                       # a cycle — already read
            ctx.visited.add(real)
            try:
                with open(include_path, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                state.skipped.append(SshConfigIssue(pattern, REASON_INCLUDE_MISSING,
                                                    include_path, source, line))
                continue
            state.files.append(include_path)
            _parse_into(text, include_path, state, ctx, depth + 1)


def _parse_into(text: str, source: str, state: _State, ctx: _Context, depth: int):
    """One pass over a config text, appending into ``state`` (Include recursion shares it)."""
    current: List[str] = []      # the concrete aliases of the active Host block
    in_block = False             # inside a Host block → directives apply
    in_match = False             # inside a Match block → every directive is dropped

    for line_number, line in _logical_lines(text):
        key, rest = _split_directive(line)
        if key is None:
            continue

        if key == "host":
            in_match = False
            in_block = True
            current = []
            for pattern in _split_values(rest):
                if pattern.startswith("!"):
                    continue                       # an exclusion, not a host
                if any(ch in pattern for ch in WILDCARD_CHARS):
                    state.skipped.append(SshConfigIssue(pattern, REASON_WILDCARD,
                                                        "", source, line_number))
                    continue
                current.append(pattern)
                state.touch(pattern, source, line_number)
            continue

        if key == "match":
            in_match = True
            in_block = False
            current = []
            state.skipped.append(SshConfigIssue(rest.strip(), REASON_MATCH,
                                                "", source, line_number))
            continue

        if key == "include":
            if not in_match:
                _handle_include(rest, source, state, ctx, depth, line_number)
            continue

        if in_match or not in_block or not current:
            continue                                # global context → ignored

        if key not in _KNOWN_OPTIONS:
            if key in PROXY_DIRECTIVES:
                for alias in current:
                    state.notes.append(SshConfigIssue(alias, NOTE_PROXY, "",
                                                      source, line_number))
            continue                                # Ciphers, forwards, … — irrelevant here

        value = _unquote(rest)
        if not value:
            continue
        for alias in current:
            _apply_option(state, ctx, alias, key, value, source, line_number)


def _apply_option(state: _State, ctx: _Context, alias: str, option: str, value: str,
                  source: str, line: int):
    """Set one option of one alias — the FIRST obtained value wins (OpenSSH rule)."""
    opts = state.options[alias]

    if option == "identityfile":
        if value.lower() == "none":
            # the documented idiom "no identity file": it CLEARS the key (last wins)
            opts["identityfile"] = ""
            return
        if "identityfile" in opts:
            if opts["identityfile"]:
                state.notes.append(SshConfigIssue(alias, NOTE_IDENTITY_EXTRA, value,
                                                  source, line))
            return
        opts["identityfile"] = expand_path_tokens(
            value,
            host=opts.get("hostname") or alias,
            user=opts.get("user") or ctx.local_user,
            home=ctx.home, local_user=ctx.local_user)
        return

    if option in opts:
        return
    if option == "port":
        try:
            opts["port"] = int(value)
        except ValueError:
            return                                  # a malformed port is ignored, like ssh
        return
    opts[option] = value


def parse_ssh_config(text: str, source: str = "", *, home: Optional[str] = None,
                     local_user: Optional[str] = None) -> SshConfigResult:
    """Parse a config TEXT into hosts + the two report lists.

    ``Include`` directives are followed on the real filesystem (relative to
    ``~/.ssh``) — ``home`` selects that root, which is what makes the function
    testable without touching the user's own config.
    """
    home = home or os.path.expanduser("~")
    if local_user is None:
        try:
            local_user = getpass.getuser()
        except Exception:  # noqa: BLE001 — no passwd entry / a locked-down host
            local_user = ""
    ctx = _Context(home=home, local_user=local_user or "")
    state = _State()
    if source:
        state.files.append(source)
        ctx.visited.add(os.path.normcase(os.path.abspath(source)))
    _parse_into(text, source, state, ctx, 0)

    hosts = []
    for alias in state.order:
        opts = state.options[alias]
        hosts.append(SshConfigHost(
            alias=alias,
            host=opts.get("hostname") or alias,
            user=opts.get("user") or ctx.local_user,
            port=int(opts.get("port") or DEFAULT_PORT),
            key_path=opts.get("identityfile", "") or "",
            source=state.source_of.get(alias, source),
            line=state.line_of.get(alias, 0),
        ))
    return SshConfigResult(
        hosts=tuple(hosts),
        skipped=tuple(state.skipped),
        notes=tuple(state.notes),
        files=tuple(state.files),
        path=source,
    )


def load_ssh_config(path: Optional[str] = None, *, home: Optional[str] = None,
                    local_user: Optional[str] = None) -> SshConfigResult:
    """Read and parse ``~/.ssh/config`` (or ``path``).

    Raises ``SshConfigError`` when the ENTRY file is missing or unreadable —
    there is nothing to show in that case. A broken ``Include`` is a skip
    record inside the result, never an exception.

    v1.5.2 (ROADMAP task 2): the ONE record of this import reaches the log (and the
    activity panel) — the summary on success, the reason on the two failure paths. The
    detail carries the PATH (never a credential: the config holds none of the app's
    secrets).
    """
    home = home or os.path.expanduser("~")
    config_path = path or default_config_path(home)
    try:
        with open(config_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except FileNotFoundError:
        log.warning(f"SSH config import: no file at {config_path} ({ERROR_MISSING})")
        raise SshConfigError(ERROR_MISSING, config_path)
    except OSError as e:
        log.error(f"SSH config import failed: {config_path} is unreadable — {e}")
        raise SshConfigError(ERROR_UNREADABLE, str(e))
    result = parse_ssh_config(text, config_path, home=home, local_user=local_user)
    log.info(f"SSH config import: {len(result.hosts)} host(s) from {config_path} "
             f"({len(result.skipped)} skipped, {len(result.notes)} note(s))")
    return result


def dedupe_hosts(hosts, existing_keys=None, key_fn=None):
    """Split hosts into ``(fresh, duplicates)`` against a key set.

    The key is ``(host, port, user)`` lower-cased for the host/user (the TXT
    import's "already on the map" rule, with the port added — the same machine
    on another port is another node). ``existing_keys`` is MUTATED with the
    accepted keys, so a caller may pass the map's keys and drop the config's own
    duplicates in the same pass.
    """
    seen = set(existing_keys or ())
    if key_fn is None:
        def key_fn(h):
            return (str(h.host).strip().lower(), int(h.port), str(h.user).strip().lower())
    fresh, duplicates = [], []
    for host in hosts:
        key = key_fn(host)
        if key in seen:
            duplicates.append(host)
            continue
        seen.add(key)
        fresh.append(host)
    return fresh, duplicates
