# -*- coding: utf-8 -*-
"""v1.1.2RC3 (AUDIT U2): saving/restoring window sizes.

User remark U2 ("saving window sizes, the main window and the terminal"):
windows got a default size on every start (the main one — resize(1200, 850), the
terminal — resize(800, 600)), and stretching did not survive a restart. Fix: on
window close, saveGeometry()/saveState() are written to ~/.sshmap/config.json
under a key; on start / window creation — they are restored.

Keys (one per window, both values inside):
  * ui_window_geometry_main      — the main window (MainWindow);
  * ui_window_geometry_terminal  — the terminal windows (SSHTerminalWindow; all
                                   terminals share the key — the last closed
                                   one is remembered).

The key value — a JSON object {"geometry": <base64>, "state": <base64>}:
  * geometry — the QByteArray saveGeometry() (window position + size);
  * state    — the QByteArray saveState() (QMainWindow state: maximized/normal,
               the docks/toolbars layout).

QByteArray is not directly JSON-serializable → base64. restoreGeometry()/
restoreState() take a QByteArray back (a symmetric pair of Qt APIs).

Headless-friendly and teardown-robust: both functions NEVER raise — no key /
a broken value / a C++ object RuntimeError → no-op + False. Saving/restoring
geometry must not break the application start or close.
"""

import base64


def _qba_to_b64(qbytearray) -> str:
    """QByteArray → a base64 string (ASCII). Empty/None → ''."""
    try:
        return base64.b64encode(bytes(qbytearray)).decode("ascii")
    except Exception:  # noqa: BLE001 — teardown/a broken object does not break saving
        return ""


def _b64_to_qba(b64str):
    """A base64 string → QByteArray; broken/empty → None.

    IMPORTANT (verified by a run, PySide6 6.11): fromBase64 expects BASE64 TEXT
    (the ascii bytes of the string), NOT already-decoded raw bytes — raw bytes
    are interpreted by Qt as the base64 alphabet and it silently returns an
    EMPTY QByteArray.
    The Python validation (validate=True) — a quick "is this even base64" check
    before calling Qt; Qt itself does the decode from the original string.
    """
    from PySide6.QtCore import QByteArray
    if not isinstance(b64str, str) or not b64str:
        return None
    try:
        raw = base64.b64decode(b64str.encode("ascii"), validate=True)
    except Exception:  # noqa: BLE001 — not base64 → no data
        return None
    if not raw:
        return None
    qba = QByteArray.fromBase64(b64str.encode("ascii"))
    if len(qba) == 0:   # the Qt decoder still refused — broken data
        return None
    return qba


def save_window_geometry(key: str, window, extra: dict = None) -> bool:
    """Save the window's saveGeometry()/saveState() to config.json under key.

    window — a QMainWindow (MainWindow / SSHTerminalWindow). True — written;
    False — the window gave no data or the config write failed. Never raises.

    v1.3.3.5: `extra` — additional TOP-LEVEL config keys written by the very same
    `save_config()` call (the terminal window merges the split state/ratio of
    `ui_terminal_split` / `ui_terminal_split_ratio` into its geometry write, so the
    restore path of a window stays ONE call and one merge-write). A non-dict extra is
    ignored; the key value itself is never overwritten by it.
    """
    try:
        from i18n import save_config
    except Exception:  # noqa: BLE001 — a flat layout without i18n — nothing to write to
        return False
    try:
        geom = _qba_to_b64(window.saveGeometry())
        state = _qba_to_b64(window.saveState())
    except Exception:  # noqa: BLE001 — a C++ object RuntimeError (teardown) etc.
        return False
    if not geom and not state:
        return False
    payload = {key: {"geometry": geom, "state": state}}
    if isinstance(extra, dict):
        for k, v in extra.items():
            if k != key:      # the geometry record is never clobbered by an extra key
                payload[k] = v
    try:
        return bool(save_config(payload))
    except Exception:  # noqa: BLE001 — save_config does not raise itself, but just in case
        return False


def restore_window_geometry(key: str, window) -> bool:
    """Restore the window's geometry/state from config.json (key key).

    True — something was restored (geometry and/or state); False — no key, a
    broken value, or the window did not accept the data. Never raises; on False
    the window keeps its default size (the resize() called earlier).
    """
    try:
        from i18n import load_config
    except Exception:  # noqa: BLE001 — a flat layout without i18n
        return False
    try:
        data = load_config().get(key)
    except Exception:  # noqa: BLE001
        return False
    if not isinstance(data, dict):
        return False

    restored = False
    geom = _b64_to_qba(data.get("geometry"))
    if geom is not None:
        try:
            window.restoreGeometry(geom)
            restored = True
        except Exception:  # noqa: BLE001 — teardown/a broken QByteArray
            pass
    state = _b64_to_qba(data.get("state"))
    if state is not None:
        try:
            window.restoreState(state)
            restored = True
        except Exception:  # noqa: BLE001
            pass
    return restored
