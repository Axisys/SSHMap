# -*- coding: utf-8 -*-
"""v0.8.2: Launching an SSH session in an alternative (system) terminal.

The application only spawns a process (subprocess.Popen) with the OS ssh
client (`ssh.exe` ships with Windows 10/11 and nearly all Linux distros) —
after launch no link to the window is needed.

SECURITY: the password is NOT passed through command-line arguments
(it would be visible in `ps`/task manager). External terminal = OS ssh:
the user types the password themselves, or key auth is used
(`ssh -i key -p port user@host`).

Settings — the single ~/.sshmap/config.json file (i18n.load_config/save_config,
atomic write), key:
    "external_terminal": "auto" | "windows_terminal" | "cmd"
                         | "x-terminal-emulator" | "gnome-terminal" | "konsole"
                         | "xfce4-terminal" | "alacritty" | "kitty"
Key absent = "auto".

v1.1.2RC1 (N2): the "conhost" preset was REMOVED — conhost.exe is not a launcher
(it does not accept /c; positional arguments are interpreted as console/process
server handles), so the assembled command was guaranteed not to work. The old
config value "conhost" is treated as "cmd" (the cmd.exe window IS the classic
conhost): the mapping lives in load_external_terminal_setting() + normalization
during legacy-file migration; build_command("conhost", ...) remains an alias
for "cmd" for direct calls.

v1.1 (ROADMAP task 7): before v1.0 the setting lived in a separate
~/.sshmap_settings.json — the application had two sources of settings. Now a
migration runs on read: if the key is missing from config.json but present in
the old file — the value is copied into config.json (save_config), and the old
file is deleted (best effort). Writes go ONLY to config.json. The preset-picker
UI — the SSHConnectDialog section (v0.9.9.2) and the "General" tab of the
settings dialog (v1.1).
"""

import os
import shutil
import subprocess
import sys
from typing import Optional, List

try:
    from .logger import get_logger
except ImportError:
    from modules.logger import get_logger

log = get_logger(__name__)

# ── Settings (single ~/.sshmap/config.json; v1.1 — ROADMAP task 7) ────────────

# Name of the OLD settings file (v0.8.2–v1.0): needed only for migration on read.
SETTINGS_FILENAME = ".sshmap_settings.json"
LEGACY_SETTINGS_FILENAME = SETTINGS_FILENAME  # alias — clearer by meaning

# External terminal setting keys (settings key values ↔ terminal ids).
# v1.1.2RC1 (N2): "conhost" removed from the list — conhost.exe is not a
# launcher (see the module docstring); the old stored value "conhost" is
# mapped to "cmd" in load_external_terminal_setting() (backward-compat).
TERMINAL_CHOICES_WINDOWS = ["auto", "windows_terminal", "cmd"]
TERMINAL_CHOICES_LINUX = [
    "auto", "x-terminal-emulator", "gnome-terminal", "konsole",
    "xfce4-terminal", "alacritty", "kitty",
]


def _settings_path() -> str:
    """v1.1: path to the SINGLE settings file — ~/.sshmap/config.json (was .sshmap_settings.json)."""
    return os.path.join(os.path.expanduser("~"), ".sshmap", "config.json")


def _legacy_settings_path() -> str:
    """Path to the OLD separate file (v0.8.2–v1.0) — for migration only."""
    return os.path.join(os.path.expanduser("~"), LEGACY_SETTINGS_FILENAME)


def _read_legacy_settings() -> Optional[dict]:
    """Contents of the old ~/.sshmap_settings.json (None — missing/corrupt)."""
    try:
        import json
        with open(_legacy_settings_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _migrate_legacy_settings() -> Optional[str]:
    """v1.1 (ROADMAP task 7): one-time migration of the key from the old file into config.json.

    Called on read when the key is still absent from config.json: the value is
    copied into config.json (save_config — atomic merge-write), then the old
    file is deleted (best effort; if the write failed — the file stays and the
    migration will repeat on the next read). Returns the migrated value or None.
    """
    legacy = _read_legacy_settings()
    if not legacy or "external_terminal" not in legacy:
        return None
    raw = str(legacy["external_terminal"]).strip().lower()
    # v1.1.2RC1 (N2): "conhost" is no longer a preset — normalize to "cmd" BEFORE
    # writing, so the dead value does not get baked into config.json.
    if raw == "conhost":
        raw = "cmd"
    try:
        from i18n import save_config as _save_cfg
        if not _save_cfg({"external_terminal": raw}):
            return raw  # write failed — return the value, keep the file
    except Exception:
        return raw
    try:
        os.remove(_legacy_settings_path())
    except OSError:
        pass  # could not delete (read-only home, etc.) — the key is already in config.json
    log.info("Migrated external_terminal setting from %s to config.json",
             LEGACY_SETTINGS_FILENAME)
    return raw


def load_external_terminal_setting() -> str:
    """Read the terminal setting from ~/.sshmap/config.json ('auto' by default).

    v1.1 (ROADMAP task 7): single settings file. If the key is absent from
    config.json but present in the old ~/.sshmap_settings.json — migration on
    read (_migrate_legacy_settings()). Invalid value → 'auto'.

    v1.1.2RC1 (N2): backward-compat — the old stored value "conhost" is
    treated as "cmd" (the config on disk is NOT rewritten, mapping on read).
    """
    value = None
    try:
        from i18n import load_config as _load_cfg
        cfg = _load_cfg() or {}
        if "external_terminal" in cfg:
            value = str(cfg.get("external_terminal", "auto")).strip().lower()
        else:
            value = _migrate_legacy_settings()
    except Exception:
        return "auto"
    if value is None:
        value = "auto"
    # v1.1.2RC1 (N2): "conhost" removed from presets — old configs are read as "cmd".
    if value == "conhost":
        value = "cmd"
    valid = set(TERMINAL_CHOICES_WINDOWS if sys.platform == "win32"
                else TERMINAL_CHOICES_LINUX)
    return value if value in valid else "auto"


def save_external_terminal_setting(value: str) -> bool:
    """Save the setting to ~/.sshmap/config.json (atomic merge-write).

    v1.1 (ROADMAP task 7): the old ~/.sshmap_settings.json is NO LONGER written;
    if it still exists with the key — load_external_terminal_setting() migrates
    it and deletes the file. False on a write error.
    """
    try:
        from i18n import save_config as _save_cfg
        return bool(_save_cfg({"external_terminal": value}))
    except Exception as e:
        log.warning("Cannot save external terminal setting: %s", e)
        return False


# ── detect_terminal ────────────────────────────────────────────────

def _which(name: str) -> Optional[str]:
    try:
        return shutil.which(name)
    except Exception:
        return None


def detect_terminal() -> Optional[str]:
    """Find an available terminal emulator on the current OS.

    Windows: wt.exe → cmd.exe (always present).
    Linux: x-terminal-emulator / gnome-terminal / konsole / xfce4-terminal /
           alacritty / kitty.
    Returns an id ("windows_terminal"/"cmd"/...) or None if nothing is found.

    v1.1.2RC1 (N2): "conhost" removed from the fallback chain — conhost.exe is
    not a launcher (see the module docstring); the cmd.exe window IS the classic
    conhost, and cmd.exe is always present on Windows, so the wt → cmd chain
    covers all cases.
    """
    forced = load_external_terminal_setting()
    if sys.platform == "win32":
        order = {
            "windows_terminal": lambda: _which("wt.exe"),
            "cmd": lambda: _which("cmd.exe"),
            # auto: wt is present on nearly all Win10/11; cmd — the guaranteed fallback
            "auto": lambda: _which("wt.exe") or _which("cmd.exe"),
        }
        finder = order.get(forced, order["auto"])
        result = finder()
        if result:
            return forced if forced in order and forced != "auto" else (
                "windows_terminal" if _which("wt.exe") else "cmd")
        # Explicitly chosen terminal not found via which → generic fallback.
        for tid in ("windows_terminal", "cmd"):
            if order[tid]():
                return tid
        return None

    # Linux / macOS
    candidates = [c for c in TERMINAL_CHOICES_LINUX if c != "auto"]
    if forced != "auto" and forced in candidates:
        if _which(forced):
            return forced
    for name in candidates:
        if _which(name):
            return name
    # macOS fallback: Terminal.app via open
    if sys.platform == "darwin":
        return "open_terminal"
    return None


def ssh_client_available() -> bool:
    return _which("ssh") is not None


# ── build_command ──────────────────────────────────────────────────

def build_ssh_args(host: str, user: str, port: int = 22,
                   key_path: Optional[str] = None,
                   jump: Optional[str] = None) -> List[str]:
    """Arguments for the OS ssh client (without 'ssh' itself).

    known_hosts — the system one (~/.ssh/known_hosts), NOT ~/.sshmap.
    """
    args = ["ssh"]
    if port and int(port) != 22:
        args += ["-p", str(int(port))]
    if key_path:
        args += ["-i", key_path]
    if jump:
        args += ["-J", jump]
    args += ["-o", "ConnectTimeout=10"]
    args.append(f"{user}@{host}" if user else host)
    return args


def _sh_quote(s: str) -> str:
    """Escape a single argument for bash -c '...' (POSIX single-quote).

    v0.9.4-fix: key paths with spaces/quotes broke the shell command assembled
    by concatenation. Used ONLY for the Linux/macOS branches where the command
    is passed as a string to `bash -c`.
    """
    return "'" + s.replace("'", "'\"'\"'") + "'"


def _shell_join(args: List[str]) -> str:
    """Join argv into a safe sh string."""
    return " ".join(_sh_quote(a) for a in args)


def _applescript_quote(s: str) -> str:
    """Escape a value for an AppleScript DOUBLE-QUOTED string literal.

    AppleScript has NO single-quoted string literal, so `_sh_quote()` — the
    POSIX helper of the `bash -c` branches — cannot be used inside an
    `osascript -e` SOURCE: the interpreter refuses to compile the script and
    Terminal.app never opens. Only the backslash and the double quote are
    special inside such a literal (the escape order matters: backslashes
    first, otherwise the escapes added for the quotes would be doubled).
    """
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


# Interpreter-driven launchers: the process runs to completion and its EXIT
# STATUS is the answer, so launch() must not report success for a source the
# interpreter refused (the osascript case above).
INTERPRETER_COMMANDS = ("osascript",)
INTERPRETER_WAIT_SEC = 10.0


def _is_interpreter_command(command: List[str]) -> bool:
    """True when the launcher is an INTERPRETER whose exit status is the answer."""
    if not command:
        return False
    return os.path.basename(command[0]) in INTERPRETER_COMMANDS


def build_command(terminal: str, host: str, user: str, port: int = 22,
                  key_path: Optional[str] = None,
                  jump: Optional[str] = None) -> List[str]:
    """The full launch command for an external terminal running ssh inside.

    - Windows Terminal: `wt.exe ssh ...`
    - cmd:              `cmd /c start "" ssh ...` (the empty window title is a
                        required positional argument of start)
    - Linux gnome-terminal and relatives: `<term> -- bash -c "ssh ...; exec bash"`
      (the window does not close when the session drops).
    The password never enters the command (see the module docstring).

    v1.1.2RC1 (N2): the "conhost" branch removed — the command `["conhost.exe",
    "cmd.exe", "/c", ssh_exe]` was not working (conhost is not a launcher,
    /c is not accepted; the old docstring "cmd/conhost: cmd /c start" disagreed
    with the real branch). The old id "conhost" is mapped to "cmd" — the
    cmd.exe window IS the classic conhost.
    """
    # v1.1.2RC1 (N2): backward-compat for direct calls with the old id.
    if terminal == "conhost":
        terminal = "cmd"

    ssh_args = build_ssh_args(host, user, port, key_path, jump)

    if terminal == "windows_terminal":
        return ["wt.exe"] + ssh_args
    if terminal == "cmd":
        # `start "" prog args`: the empty title is mandatory, otherwise the first
        # argument is eaten as the window title. We take the full path to ssh —
        # `start` looks in the current directory first.
        ssh_exe = _which("ssh") or "ssh"
        return ["cmd.exe", "/c", "start", "", ssh_exe] + ssh_args[1:]
    if terminal == "open_terminal":  # macOS
        # v0.9.4-fix: `open -a Terminal bash -c ...` does not work — open does
        # not pass arguments that way. The correct way is osascript: open
        # Terminal.app and run the command in it (the window survives the
        # session drop thanks to `exec bash`).
        # The `-e` SOURCE is AppleScript, so the ssh command it carries is
        # escaped as an AppleScript literal — never with the POSIX `_sh_quote()`
        # of the `bash -c` branches below.
        script = f"{_shell_join(ssh_args)}; exec bash"
        return ["osascript", "-e",
                'tell application "Terminal" to do script ' + _applescript_quote(script)]
    # Linux family: gnome-terminal/konsole/xfce4-terminal/alacritty/kitty/
    # x-terminal-emulator
    shell_cmd = f"{_shell_join(ssh_args)}; exec bash"
    if terminal in ("gnome-terminal", "konsole", "xfce4-terminal",
                    "x-terminal-emulator", "alacritty", "kitty"):
        exe = _which(terminal) or terminal
        if terminal == "konsole":
            return [exe, "-e", "bash", "-c", shell_cmd]
        if terminal == "kitty":
            return [exe, "bash", "-c", shell_cmd]
        if terminal == "alacritty":
            return [exe, "-e", "bash", "-c", shell_cmd]
        # gnome-terminal / xfce4-terminal / x-terminal-emulator
        return [exe, "--", "bash", "-c", shell_cmd]
    raise ValueError(f"Unknown terminal id: {terminal!r}")


# ── launch ─────────────────────────────────────────────────────────

def launch(command: Optional[List[str]] = None, host: str = "", user: str = "",
           port: int = 22, key_path: Optional[str] = None,
           jump: Optional[str] = None) -> bool:
    """Spawn the external terminal process (subprocess.Popen).

    Two modes (AUDIT v0.8.3 #4 — explicit signature instead of kwargs.pop):
      - command is given  → launch it as-is;
      - command=None      → detect_terminal() + build_command(host, user, ...);
        a call without host now gives a clear error instead of KeyError.
    Windows: CREATE_NEW_CONSOLE — the window lives its own life
    (AUDIT v0.8.3 #2: DETACHED_PROCESS from the old code was removed — the
    flags are mutually exclusive, only the second overwrite took effect).
    Returns True/False; a Popen exception is logged and turned into False.
    An INTERPRETER launcher (`_is_interpreter_command()`, the osascript branch)
    is WAITED for: a source the interpreter refused must not be reported as a
    launched terminal.
    """
    if command is None:
        if not host:
            log.error("launch() without command requires host")
            return False
        term = detect_terminal()
        if not term:
            return False
        command = build_command(term, host, user, port, key_path, jump)
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
        )
        if _is_interpreter_command(command):
            try:
                status = proc.wait(timeout=INTERPRETER_WAIT_SEC)
            except subprocess.TimeoutExpired:
                log.error("Interpreter %s did not return within %.0f s",
                          command[0], INTERPRETER_WAIT_SEC)
                return False
            if status:
                log.error("Interpreter %s exited with status %s — nothing was launched",
                          command[0], status)
                return False
        log.info("External terminal launched: %s", command[0])
        return True
    except FileNotFoundError as e:
        log.error("External terminal binary not found (%s): %s", command[0], e)
        return False
    except OSError as e:
        log.error("Popen failed for external terminal: %s", e)
        return False


def connect_external(host: str, user: str, port: int = 22,
                     key_path: Optional[str] = None,
                     jump: Optional[str] = None) -> tuple:
    """The full path: detect → build → launch.

    Returns (ok: bool, error_code: str|None):
      error_code ∈ {None, 'no_ssh_client', 'no_terminal', 'popen_failed'}.
    """
    if not ssh_client_available():
        return False, "no_ssh_client"
    term = detect_terminal()
    if not term:
        return False, "no_terminal"
    ok = launch(build_command(term, host, user, port, key_path, jump))
    return (True, None) if ok else (False, "popen_failed")
