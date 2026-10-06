# -*- coding: utf-8 -*-
"""Atomic writes — the ONE mechanism behind every user file of the application (AGENTS.md §4.4).

`publish_atomic(path, write_temp)` is the publish: the caller fills a UNIQUE provisional file
(`<name>.<random>.tmp`, same folder) and it is fsynced and `os.replace()`-d onto `path`, so a reader
sees the whole document or the previous one, and a failed write removes the provisional file.
`write_json_atomic()` adds the READ-MODIFY-WRITE half under `atomic_lock(path)` — the lock covers
the read, the merge and the publish, which is what a MERGE-writer needs — and `dump_json()` is the
JSON `write_temp`. Cross-process writers are deliberately OUT of scope and DECLARED, the ONE answer
the known_hosts store gives as well: the lock is a `threading.Lock` (this application instance) and
the atomic replace is what keeps a second instance from ever reading a truncated file.
Mechanism — `DOCUMENTATION.md` §71.
"""
import json
import os
import stat
import tempfile
import threading

#: The suffix of the provisional file — a crash orphan reads as `<name>.<random>.tmp`.
TEMP_SUFFIX = ".tmp"

_locks = {}
_locks_guard = threading.Lock()


def _default_mode() -> int:
    """The mode a published file gets: what a plain `open(path, "w")` would have used (umask read
    ONCE, because `os.umask()` is process-global and must not be touched per write)."""
    try:
        mask = os.umask(0)
        os.umask(mask)
        return 0o666 & ~mask
    except OSError:
        return 0o644


#: The mode of a published file — one answer for every writer of the family.
TEMP_MODE = _default_mode()


def atomic_lock(path) -> threading.RLock:
    """The ONE lock of `path`'s read-modify-write: every writer of the same file gets one object.

    A re-entrant lock, because a writer may hold it and call another function of this module.
    """
    key = os.path.normcase(os.path.abspath(str(path)))
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _locks[key] = lock
        return lock


def read_json(path) -> dict:
    """The current document of a merge-writer: `{}` when the file is missing, broken or not an object."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def dump_json(path, data, indent=2) -> None:
    """The JSON `write_temp`: the whole document into `path`, utf-8, no `\\uXXXX` escaping."""
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=indent)


def _fsync(path) -> None:
    """Put the bytes of a WRITTEN provisional file on the disk BEFORE it is published.

    The mode its WRITER left is preserved: a `write_temp` that COPIES a file (`shutil.copy2`) brings
    the SOURCE's own mode along, so a READ-ONLY source reaches this function unwritable and
    `os.open(…, os.O_RDWR)` would refuse the handle. Write access is granted for the ONE call and
    put back, because `os.replace()` publishes this inode's mode.
    """
    mode = stat.S_IMODE(os.stat(path).st_mode)
    writable = bool(mode & 0o200)
    if not writable:
        os.chmod(path, mode | 0o200)
    try:
        handle = os.open(path, os.O_RDWR)
        try:
            os.fsync(handle)
        finally:
            os.close(handle)
    finally:
        if not writable:
            os.chmod(path, mode)


def _remove(path) -> None:
    """Best-effort delete of a provisional file (a failure here is never the caller's error)."""
    if not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass


def publish_atomic(path, write_temp) -> None:
    """Publish `path` in ONE visible step; RAISES the failure (the caller owns the answer).

    `write_temp(temp_path)` fills the provisional file. The name is UNIQUE and PREFIXED with the
    target's own name — two writers never share it, and a crash orphan is recognisable — and the
    replace happens in the SAME folder, hence on the same file system. The published file keeps the
    mode its writer gave it (`TEMP_MODE` for a plain write, the SOURCE's for a copy), so a read-only
    source is copied instead of refused.
    """
    directory = os.path.dirname(str(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    handle, temp = tempfile.mkstemp(prefix=os.path.basename(str(path)) + ".", suffix=TEMP_SUFFIX,
                                    dir=directory or ".")
    os.close(handle)
    try:
        # mkstemp creates the file 0600; the published file keeps the mode a plain write would give.
        os.chmod(temp, TEMP_MODE)
        write_temp(temp)
        _fsync(temp)
        os.replace(temp, path)
    except BaseException:
        _remove(temp)
        raise


def write_json_atomic(path, data, merge: bool = False, reader=None, indent: int = 2) -> bool:
    """Write a JSON document ATOMICALLY; False on any error, never a raise.

    `merge=True` re-reads the file INSIDE the lock (`reader` — a zero-argument callable, default
    `read_json(path)`) and updates it with `data`: the read, the merge and the publish are ONE
    critical section, so two writers cannot publish each other's stale snapshot.
    """
    try:
        with atomic_lock(path):
            payload = data
            if merge:
                current = read_json(path) if reader is None else reader()
                if not isinstance(current, dict):
                    current = {}
                current.update(data)
                payload = current
            publish_atomic(path, lambda temp: dump_json(temp, payload, indent=indent))
        return True
    except (OSError, TypeError, ValueError):
        return False
