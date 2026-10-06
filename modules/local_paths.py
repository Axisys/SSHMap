# -*- coding: utf-8 -*-
"""The ONE resolver of a local path a user TYPED — `~` and relative paths (AGENTS.md §4.4).

`resolve_local_path()` is what turns the string in a field into the path the OS is asked to open: `~` is
expanded through the platform and a relative path is joined to a base directory (the caller's, otherwise
the process's current one). It exists because the connect path handed `key_path` to paramiko AS TYPED —
paramiko expands only its OWN known_hosts path — and the background loader checked `os.path.isfile()` on
the same raw string, so `~/keys/id_ed25519` failed as a literal path in both.

An ABSOLUTE path is returned UNCHANGED (never re-normalised and never case-folded), so a caller can
compare the answer with the string it stored; a non-string or an empty value answers `""` and the
function never raises. Mechanism — `DOCUMENTATION.md` §16."""

import os


def resolve_local_path(text, base_dir=None) -> str:
    """The OS path of `text`: `~` expanded, a relative path joined to `base_dir` (or the CWD).

    `base_dir` is the ONE way a caller says "relative to HERE" — the project loader passes the folder of
    the project file it is reading, everything else keeps the process's current directory. An absolute
    path (after the expansion) is answered as it is, so `"/k/id_ed25519"` stays byte for byte what the
    caller stored. Never raises: an unusable value answers `""` (an empty path is "no path" everywhere).
    """
    if text is None:
        return ""
    try:
        raw = str(text)
    except Exception:  # noqa: BLE001 — a __str__ that raises is not a path
        return ""
    if not raw:
        return ""
    try:
        expanded = os.path.expanduser(raw)
    except Exception:  # noqa: BLE001 — a platform without a home directory
        expanded = raw
    if expanded != raw:
        # A `~` was really expanded: normalise the result so a mixed separator spelling ("~/a/b")
        # answers the ONE path the platform spells, while a path WITHOUT a `~` is never touched.
        try:
            expanded = os.path.normpath(expanded)
        except Exception:  # noqa: BLE001
            pass
    if not expanded:
        return ""
    try:
        if os.path.isabs(expanded):
            return expanded
    except Exception:  # noqa: BLE001
        return expanded

    base = base_dir
    if base is None:
        try:
            base = os.getcwd()
        except Exception:  # noqa: BLE001 — a process without a current directory
            base = ""
    if not base:
        return expanded
    try:
        base = os.path.expanduser(str(base))
    except Exception:  # noqa: BLE001
        pass
    try:
        return os.path.normpath(os.path.join(base, expanded))
    except Exception:  # noqa: BLE001
        return expanded
