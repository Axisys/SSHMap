# -*- coding: utf-8 -*-
"""v0.9.7: autosave + a ring buffer of project backups (ROADMAP v0.9.7).

Goal — a safety net against JSON corruption / accidental loss of edits:

  * autosave — a full project serialization (same format as save_project;
    NO passwords in it: server_data_to_dict strips them) is written to
    ``~/.sshmap/autosave/<key>.json`` on a timer (interval from config, default 60 s),
    only when dirty and only if a project file is open;
  * backups — a ring buffer of N files (default 10) in ``~/.sshmap/backups/``:
    on every manual save of this file the pre-save version is shifted into
    slot 001, older slots move to +1, overflow beyond N is deleted;
  * restore — an atomic copy of the backup/autosave back into the project file.

Layout (same ~/.sshmap root as config.json / known_hosts / logs):

    ~/.sshmap/autosave/<key>.json        — the project's last autosave
    ~/.sshmap/backups/<key>_001.json     — the newest backup (previous version of the file)
    ...
    ~/.sshmap/backups/<key>_NNN.json     — the oldest retained backup

``<key>`` = sha1[:16] of the normalized absolute project file path: stable
across sessions, distinguishes files with the same name in different directories.

A module without Qt dependencies — tested with plain python / offscreen (the
storage/project.py pattern). All functions are "quiet": a corrupted/missing file
neither breaks startup nor saving — they return None/[] or log.
"""
import hashlib
import json
import os
import shutil
from typing import Dict, List, Optional

# ── Paths and defaults ────────────────────────────────────────────────────────────

_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".sshmap")
AUTOSAVE_DIR = os.path.join(_CONFIG_DIR, "autosave")
BACKUPS_DIR = os.path.join(_CONFIG_DIR, "backups")

# ROADMAP v0.9.7: interval is configurable, default ~60 s; a ring buffer of N files,
# default 10. Config — the existing ~/.sshmap/config.json (load_config from i18n):
#   autosave_enabled       bool, default True
#   autosave_interval_sec  int,  default 60
#   backup_count           int,  default 10
# A settings dialog for these keys will appear in v1.1 (ROADMAP).
DEFAULT_AUTOSAVE_ENABLED = True
DEFAULT_AUTOSAVE_INTERVAL_SEC = 60
DEFAULT_BACKUP_COUNT = 10

_MIN_INTERVAL_SEC = 5            # protection against typos "1" / "0" in the config
_MAX_INTERVAL_SEC = 24 * 3600    # and against "999999"
_MIN_BACKUPS = 1
_MAX_BACKUPS = 100


# ── Project key ──────────────────────────────────────────────────────────────

def project_key(project_path: str) -> str:
    """Stable key of a project file: sha1[:16] of the normalized absolute path.

    normcase — case/separator insensitivity on Windows; abspath —
    relative and absolute records of the same file yield one key.
    """
    norm = os.path.normcase(os.path.abspath(project_path))
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def autosave_path_for(project_path: str) -> str:
    """Autosave path for a project file."""
    return os.path.join(AUTOSAVE_DIR, project_key(project_path) + ".json")


def backup_path_for(project_path: str, slot: int) -> str:
    """Backup path in the ring. Slot 1 = the newest (the file version before the last save)."""
    return os.path.join(BACKUPS_DIR, f"{project_key(project_path)}_{slot:03d}.json")


# ── Settings ─────────────────────────────────────────────────────────────────

def get_autosave_settings() -> Dict:
    """Reads settings from ~/.sshmap/config.json (i18n load_config, never fails).

    Returns {"enabled": bool, "interval_sec": int, "backup_count": int}.
    Values outside sane ranges are clamped; corrupt values → the default.
    """
    cfg: dict = {}
    try:
        from i18n import load_config
        cfg = load_config() or {}
    except Exception:  # noqa: BLE001 — the config is optional, defaults matter more
        pass

    def _int(value, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    enabled = _bool_setting(cfg.get("autosave_enabled", DEFAULT_AUTOSAVE_ENABLED))
    interval = max(_MIN_INTERVAL_SEC, min(
        _int(cfg.get("autosave_interval_sec"), DEFAULT_AUTOSAVE_INTERVAL_SEC),
        _MAX_INTERVAL_SEC))
    backups = max(_MIN_BACKUPS, min(
        _int(cfg.get("backup_count"), DEFAULT_BACKUP_COUNT),
        _MAX_BACKUPS))
    return {"enabled": enabled, "interval_sec": interval, "backup_count": backups}


#: The spellings a HAND-EDITED config may use for "off" / "on". `bool("false")` is True,
#: so the raw value cannot be coerced — the ON spellings are listed for symmetry and an
#: unusable value falls back to the default.
_FALSE_WORDS = ("false", "0", "no", "off", "disabled")
_TRUE_WORDS = ("true", "1", "yes", "on", "enabled")


def _bool_setting(value, default: bool = True) -> bool:
    """A REAL bool out of a config value (`get_autosave_settings()`'s `autosave_enabled`).

    A `bool` answers itself, a number answers `!= 0`, and a STRING is read as one of the
    declared spellings (`"false"` / `"0"` / `"no"` mean OFF — the docstring's promise
    "corrupt values → the default" holds for anything unusable).
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        word = value.strip().lower()
        if word in _FALSE_WORDS:
            return False
        if word in _TRUE_WORDS:
            return True
    return bool(default)


# ── Atomic write (save_project / save_config pattern) ────────────────────

def atomic_write_json(path: str, data: dict) -> None:
    """Atomic JSON write: tmp + fsync + os.replace.

    A crash/power loss mid-write corrupts neither the autosave nor a backup —
    replace either happens in full or not at all (v0.9.3 fix for save_project).
    A FAILED write removes the provisional file, so a rejected path leaves no
    `*.tmp` behind (the error still propagates to the caller).
    """
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except OSError:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def read_json(path: str) -> Optional[dict]:
    """Read a JSON dict; None on missing/corrupt (quiet — see the module docstring)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _atomic_copy(src: str, dst: str) -> None:
    """Atomic file copy: copy2 to tmp + os.replace.

    copy2 preserves mtime — for backups this is "when the version was made"
    (the "Modified" column in the backups dialog). A FAILED copy removes the
    provisional file (the `atomic_write_json` guard), so no `*.tmp` survives
    a rejected destination.
    """
    directory = os.path.dirname(dst)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp_path = dst + ".tmp"
    try:
        shutil.copy2(src, tmp_path)
        os.replace(tmp_path, dst)
    except OSError:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


# ── Autosave (ROADMAP v0.9.7 #1, #3) ───────────────────────────────────

def write_autosave(project_path: str, data: dict) -> str:
    """Write the project's last autosave. Returns the file path."""
    path = autosave_path_for(project_path)
    atomic_write_json(path, data)
    return path


def read_autosave(project_path: str) -> Optional[dict]:
    """Content of the last autosave (None — missing/corrupt)."""
    return read_json(autosave_path_for(project_path))


def autosave_mtime(project_path: str) -> Optional[float]:
    """Autosave mtime (None if the file is absent)."""
    path = autosave_path_for(project_path)
    try:
        return os.path.getmtime(path) if os.path.isfile(path) else None
    except OSError:
        return None


def autosave_is_newer(project_path: str) -> bool:
    """ROADMAP v0.9.7 #3: is the autosave newer than the file on disk?

    Only an mtime comparison — "newness" is determined by the file system,
    with no trust in the content (a corrupt autosave is rejected by read_autosave).
    """
    a = autosave_path_for(project_path)
    if not (os.path.isfile(a) and os.path.isfile(project_path)):
        return False
    try:
        return os.path.getmtime(a) > os.path.getmtime(project_path)
    except OSError:
        return False


# ── Ring buffer of backups (ROADMAP v0.9.7 #2) ─────────────────────────────

def rotate_backups(project_path: str, max_count: int = DEFAULT_BACKUP_COUNT) -> List[str]:
    """Shift the ring buffer and put the current file into slot 1.

    Called BEFORE overwriting the project file (from MainWindow._do_save): the slots
    receive the "pre-save" version — a rollback to previous versions of the file.
    Slot i → i+1 (the shift goes from old to new), overflow beyond max_count
    is deleted (relevant if backup_count in the config was reduced).

    Returns the list of existing slots (newest first). The project file
    is absent (first save of a new path) → [] and silence.
    """
    if not os.path.isfile(project_path):
        return []
    for slot in range(max_count, 1, -1):
        src = backup_path_for(project_path, slot - 1)
        if os.path.isfile(src):
            _atomic_copy(src, backup_path_for(project_path, slot))
    # Leftovers beyond the new max_count (N reduced in the config).
    # v1.0-fix (audit #5): we scan up to the hard limit _MAX_BACKUPS, not a fixed
    # window of 63 slots — earlier when backup_count was reduced (e.g. 100 → 1) slots beyond
    # max_count+63 remained on disk forever.
    for slot in range(max_count + 1, _MAX_BACKUPS + 1):
        extra = backup_path_for(project_path, slot)
        if os.path.isfile(extra):
            try:
                os.remove(extra)
            except OSError:
                pass
    _atomic_copy(project_path, backup_path_for(project_path, 1))
    return list_backups(project_path, max_count)


def list_backups(project_path: str, max_count: int = DEFAULT_BACKUP_COUNT) -> List[Dict]:
    """Existing backups, newest first: [{path, slot, mtime, size}, ...]."""
    items = []
    for slot in range(1, max_count + 1):
        p = backup_path_for(project_path, slot)
        if os.path.isfile(p):
            try:
                st = os.stat(p)
                items.append({"path": p, "slot": slot, "mtime": st.st_mtime, "size": st.st_size})
            except OSError:
                continue
    return items


def restore_to_project(source_path: str, project_path: str) -> None:
    """Copy a backup/autosave back into the project file (atomically).

    Raises an exception on error — the decision about the user message is made by
    the caller (MainWindow._restore_from_source).
    """
    if not os.path.isfile(source_path):
        raise FileNotFoundError(f"Backup source not found: {source_path}")
    _atomic_copy(source_path, project_path)
