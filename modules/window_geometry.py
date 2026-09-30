# -*- coding: utf-8 -*-
"""Saving and restoring window sizes, states and the main splitter (`AGENTS.md` §4.4, §6).

On close, `saveGeometry()` / `saveState()` are written to `~/.sshmap/config.json`; on start and on
window creation they are restored. The keys:
  * `ui_window_geometry_main` — the main window; `ui_window_geometry_terminal` — the terminal windows
    (all of them share the key: the last closed one is remembered). Each value is a JSON object
    `{"geometry": <base64>, "state": <base64>}` — the QByteArray pair of Qt's symmetric APIs (a
    QByteArray is not JSON-serializable, hence base64; `state` carries maximized/normal and the
    docks/toolbars layout);
  * `ui_splitter_state` — `base64(QSplitter.saveState())` of the main window's [sidebar | map] divider:
    a plain base64 STRING (one splitter, one window), saved next to the main geometry and applied LAST
    on startup (after `restoreState()` and the collapsed-panel state); both never raise — no key, a broken value or a C++ RuntimeError is a no-op + False."""

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


# ── the panel widths ─────────────────────────────────────────────────────────
# `saveState()` of a QMainWindow covers the dock/toolbar layout, NOT the inner QSplitter of the
# central widget — the sidebar/map divider was the one piece of window state that did not survive
# a restart. The key `ui_splitter_state` holds base64(splitter.saveState()), the
# `ui_window_geometry_*` shape, so a broken value is indistinguishable from "no key".


def splitter_state_b64(splitter) -> str:
    """QSplitter.saveState() → a base64 string ('' — a broken/absent splitter)."""
    try:
        return _qba_to_b64(splitter.saveState())
    except Exception:  # noqa: BLE001 — teardown / a dead C++ object
        return ""


def save_splitter_state(key: str, splitter, extra: dict = None) -> bool:
    """Save the splitter layout (the panel widths) to config.json under `key`.

    v1.3.3.6: called at the start of `MainWindow.closeEvent` next to
    `save_window_geometry("ui_window_geometry_main", …)`. `extra` — additional
    TOP-LEVEL keys of the very same `save_config()` call (the
    `save_window_geometry` convention: one merge-write per window; the key itself
    is never clobbered by an extra). True — written; False — no data / no i18n /
    a failed write. Never raises.
    """
    state = splitter_state_b64(splitter)
    if not state:
        return False
    payload = {key: state}
    if isinstance(extra, dict):
        for k, v in extra.items():
            if k != key:
                payload[k] = v
    try:
        from i18n import save_config
    except Exception:  # noqa: BLE001 — a flat layout without i18n — nothing to write to
        return False
    try:
        return bool(save_config(payload))
    except Exception:  # noqa: BLE001 — save_config does not raise itself, but just in case
        return False


def restore_splitter_state(key: str, splitter) -> bool:
    """Restore the splitter layout from config.json (key key).

    True — the state was applied; False — no key, a broken value, a dead C++ object
    or a `restoreState()` that refused the data. Never raises: on False the caller
    keeps the sizes it already has (the 250/950 defaults of `_setup_ui`).
    """
    try:
        from i18n import load_config
        data = load_config().get(key)
    except Exception:  # noqa: BLE001 — a flat layout without i18n / a broken config
        return False
    qba = _b64_to_qba(data)
    if qba is None:
        return False
    try:
        return bool(splitter.restoreState(qba))
    except Exception:  # noqa: BLE001 — teardown / a broken QByteArray
        return False
