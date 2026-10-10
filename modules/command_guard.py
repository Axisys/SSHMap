# -*- coding: utf-8 -*-
"""The command guard — ONE PURE classifier over a FINAL command string, and ONE confirmation per RUN.

The gate sits where the LAST chance to notice a mistake is: the run's own boundary
(`PluginManager._start_command_run()`, so both the core's "Run a command on servers…" door and every
plugin's `ctx.run_command()` pass it) and the `Enter` that SUBMITS a multi-input line. The policy is the
boolean `guard_commands` of `~/.sshmap/config.json` — CONFIG and never the project — and its default is
ON: a false positive costs one dialog, a false negative costs the fleet. It is a CONFIRMATION and never a
lock. `dangerous_token()` / `needs_confirmation()` / `guard_enabled()` / `excerpt()` are PURE; the dialog
is the module attribute seam and a guard that cannot ask REFUSES. Rule and owner — `AGENTS.md` §4.30;
mechanism — `DOCUMENTATION.md` §74.
"""

import re

try:  # pragma: no cover — Qt is a hard dependency of the application
    from PySide6.QtWidgets import QMessageBox
except ImportError:
    QMessageBox = None

from i18n import load_config, t

GUARD_COMMANDS_KEY = "guard_commands"   # the policy: the guard is ON unless the user turns it off
MAX_COMMAND_CHARS = 4096                # the classification's input bound (a policy, not a parser)
SHOWN_CHARS = 200                       # the excerpt the dialog prints

#: The words a shell puts IN FRONT of the real command (they are skipped, never matched).
WRAPPERS = ("sudo", "doas", "env", "nohup", "time", "xargs", "watch")
REBOOT_WORDS = ("reboot", "shutdown", "halt", "poweroff")
PARTITION_WORDS = ("fdisk", "parted", "diskpart")
KILL_WORDS = ("kill", "pkill", "killall")
REMOVE_WORDS = ("remove",)              # the package managers' own verb (`apt remove`)
MKFS_WORD = "mkfs"                      # the family's shortest spelling (`mkfs`, `mkfs.ext4`, …)

TOKEN_RM = "rm -rf"                     # the danger is the FLAG PAIR, so the token is the shape
TOKEN_DD = "dd"
TOKEN_KILL = "kill -9"
TOKEN_KILL_ONE = "kill -1"
TOKEN_FORK_BOMB = "fork bomb"

#: The families the classifier knows. The token it answers is the MATCHED spelling (`shutdown`,
#: `mkfs.ext4`, …) except where the danger is a flag pair or a shape (`rm -rf`, `kill -9`, `fork bomb`).
FAMILIES = ("reboot", "rm", "remove", "mkfs", "dd", "wipefs", "partition", "userdel", "kill",
            "fork_bomb")

_SEGMENT_SPLIT_RE = re.compile(r"[;|&\n\r()`]+")
_FUNCTION_RE = re.compile(r"([:\w]+)\(\)\{([^}]*)\}")


def _text(value) -> str:
    """One value as a stripped string (a foreign type → "" — never an exception)."""
    try:
        return str(value if value is not None else "")
    except Exception:  # noqa: BLE001 — a broken __str__ is "no command"
        return ""


def _squash(text: str) -> str:
    """The text without ANY whitespace — the normalised form the shape families are read in."""
    return re.sub(r"\s+", "", text)


def _basename(word: str) -> str:
    """The lower-cased last path component of a word (`/sbin/reboot` and `sudo` → `reboot`, `sudo`)."""
    return word.replace("\\", "/").rsplit("/", 1)[-1].lower()


def _words(segment: str) -> list:
    """A segment's words, QUOTE-AWARE: a quoted run is ONE word (its quotes dropped)."""
    out, token, quote, index = [], [], "", 0
    while index < len(segment):
        ch = segment[index]
        if quote:
            if ch == quote:
                quote = ""
            else:
                token.append(ch)
        elif ch in "\"'":
            quote = ch
        elif ch == "\\" and index + 1 < len(segment):
            index += 1
            token.append(segment[index])
        elif ch.isspace():
            if token:
                out.append("".join(token))
                token = []
        else:
            token.append(ch)
        index += 1
    if token:
        out.append("".join(token))
    return out


def _segments(command: str) -> list:
    """The command split on the shell separators (`;`, `|`, `&`, a newline, a parenthesis, a backtick)."""
    return [part for part in _SEGMENT_SPLIT_RE.split(command) if part.strip()]


def _flag_cluster(word: str) -> str:
    """The letters of a SHORT flag cluster (`-rfv` → `rfv`); "" for a long flag or a plain word."""
    if not word.startswith("-") or word.startswith("--"):
        return ""
    return word[1:]


def _has_recursive(words) -> bool:
    """Is a recursive flag among the segment's words (`-r`, `-R`, `-rf`, `--recursive`)? PURE."""
    for word in words:
        if word in ("-r", "-R", "--recursive"):
            return True
        cluster = _flag_cluster(word)
        if cluster and ("r" in cluster or "R" in cluster):
            return True
    return False


def _has_force(words) -> bool:
    """Is a force flag among the segment's words (`-f`, `-rf`, `--force`)? PURE."""
    for word in words:
        if word in ("-f", "--force"):
            return True
        cluster = _flag_cluster(word)
        if cluster and "f" in cluster:
            return True
    return False


def _dd_target(rest) -> bool:
    """Does `dd` write to a DEVICE (`of=/dev/…`, `of=/dev/null` excluded)? PURE."""
    for word in rest:
        low = word.lower()
        if low.startswith("of=/dev/"):
            return low.split("of=", 1)[1].rstrip("/") != "/dev/null"
    return False


def _kill_token(words) -> str:
    """The token of a `kill` naming a fatal signal (`-9`/`-KILL`) or the whole-table target (`-1`)."""
    low = [word.lower() for word in words]
    for index, word in enumerate(low):
        if word in ("-1",):
            return TOKEN_KILL_ONE
        if word in ("-9", "-kill", "-sigkill"):
            return TOKEN_KILL
        if word in ("-s", "--signal") and index + 1 < len(low):
            nxt = low[index + 1].lstrip("-")
            if nxt in ("9", "kill", "sigkill"):
                return TOKEN_KILL
            if nxt in ("1", "hup"):
                return TOKEN_KILL_ONE
    return ""


def _fork_bomb(text: str) -> bool:
    """The whitespace-normalised SELF-REPLICATING function (`:(){ :|:& };:` and its re-spellings)."""
    for match in _FUNCTION_RE.finditer(text):
        name, body = match.group(1), match.group(2)
        if name and name in body and "|" in body and "&" in body:
            return True
    return False


def _segment_token(words) -> str:
    """The token of ONE segment — the FIRST destructive word (or flag pair / shape) it carries."""
    for index, word in enumerate(words):
        base = _basename(word)
        if base in REBOOT_WORDS or base in PARTITION_WORDS or base in REMOVE_WORDS:
            return base
        if base in ("wipefs", "userdel"):
            return base
        if base == MKFS_WORD or base.startswith("mkfs."):
            return base
        if base == "dd" and _dd_target(words[index + 1:]):
            return TOKEN_DD
        if base == "rm" and _has_recursive(words) and _has_force(words):
            return TOKEN_RM
        if base in KILL_WORDS:
            token = _kill_token(words)
            if token:
                return token
    return ""


def dangerous_token(command) -> str:
    """The token of the first destructive shape in a FINAL command string; "" when nothing matched.

    PURE and it never raises: a foreign value, a broken quote and a huge string are "no match"
    (`MAX_COMMAND_CHARS` bounds what is really classified). The match is DELIBERATELY generous — a
    destructive word is looked for at ANY word position of ANY segment, so a `git`/`docker` prefix, a
    wrapper or a pipeline never hides it — because a false positive costs one dialog.
    """
    text = _text(command)[:MAX_COMMAND_CHARS]
    if not text.strip():
        return ""
    if _fork_bomb(_squash(text)):
        return TOKEN_FORK_BOMB
    for segment in _segments(text):
        words = _words(segment)
        while words and _basename(words[0]) in WRAPPERS:   # a wrapper is never the command
            words = words[1:]
        token = _segment_token(words)
        if token:
            return token
    return ""


def guard_enabled(cfg=None) -> bool:
    """Is the command guard armed? — the CONFIG boolean `guard_commands`, ON by default.

    A missing key, a foreign type and an unreadable store all answer the declared default (True): the
    guard exists for the user who never read a document, so only an explicit `false` turns it off.
    """
    cfg = load_config() if cfg is None else cfg
    try:
        value = cfg.get(GUARD_COMMANDS_KEY)
    except Exception:  # noqa: BLE001 — a broken store keeps the declared default
        return True
    return value if isinstance(value, bool) else True


def needs_confirmation(command, cfg=None) -> str:
    """The token that makes a command ask before it runs — "" when it may go ahead. PURE."""
    if not guard_enabled(cfg):
        return ""
    return dangerous_token(command)


def excerpt(command) -> str:
    """The command as the dialog prints it: one line, capped at `SHOWN_CHARS`. PURE."""
    text = " ".join(_text(command).split())
    return text if len(text) <= SHOWN_CHARS else text[:SHOWN_CHARS] + "…"


def confirmation_text(command, token, count=1) -> str:
    """The RUN's ONE sentence (`guard.command.text`). PURE."""
    return t("guard.command.text", command=excerpt(command), token=str(token), count=int(count or 1))


def broadcast_text(line, token, count=1) -> str:
    """The multi-input submission's ONE sentence (`guard.command.broadcast`). PURE."""
    return t("guard.command.broadcast", command=excerpt(line), token=str(token),
             count=int(count or 1))


def _ask(text: str, parent=None) -> bool:
    """The ONE dialog: a `QMessageBox` whose DEFAULT button is No, the module attribute being the seam.

    A build that cannot show a dialog answers False — the guard is a REFUSAL by default, never a silent
    pass; `parent=None` is legal Qt and therefore still asked.
    """
    if QMessageBox is None:
        return False
    try:
        box = QMessageBox(parent)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(t("guard.title"))
        box.setText(str(text))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes
    except Exception:  # noqa: BLE001 — a dialog that cannot open never green-lights a command
        return False


def confirm(command, token, count=1, plugin_id="", parent=None) -> bool:
    """The RUN's question — ONE dialog per run, the node count NAMED in it. True when confirmed.

    `plugin_id` is accepted for the caller's sake (the sentence names the count, never the author's
    strings) and is deliberately not printed: the dialog shows the MATCHED token and the command.
    """
    return _ask(confirmation_text(command, token, count=count), parent)


def confirm_broadcast(line, token, count=1, parent=None) -> bool:
    """The multi-input submission's question — ONE dialog per `Enter`. True when confirmed."""
    return _ask(broadcast_text(line, token, count=count), parent)
