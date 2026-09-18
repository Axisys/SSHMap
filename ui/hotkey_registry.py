# -*- coding: utf-8 -*-
"""v1.3.2 (ROADMAP v1.3.2, task 1): the action registry of the configurable hotkeys.

SINGLE SOURCE OF TRUTH for the global keyboard shortcuts of the main window: menu
QActions and QShortcuts are created WITHOUT a literal sequence and receive it from
here — ``MainWindow._apply_hotkeys()`` at startup (after the UI construction) and
live after the settings dialog's OK (``QAction.setShortcut`` / ``QShortcut.setKey``),
without a restart. No literal ``"Ctrl+…"`` is scattered across the modules any more.

The registry is one declarative list ``{action_id: {...}}``:

* ``label``   — the i18n key of the action's NAME. It REUSES the existing menu keys
                (no new strings for the settings table); the value is a key, not a
                literal.
* ``default`` — the sequence of v1.3.1.1 (the behavior documented for this version).
                v1.3.3.3: an EMPTY default is a first-class value — see below.
* ``alt``     — optional extra sequences that follow the DEFAULT only (the legacy
                redo alias Ctrl+Y): they are dropped as soon as the user picks a
                sequence of their own for that action.
* ``dynamic`` — the sequence is installed ONLY in a certain mode (multi-input F12,
                v1.2.3 / v1.2.4-fix): ``apply_to()`` skips such actions, the mode
                implementation owns them (``SshMixin._sync_multi_shortcut``).

**The empty default (v1.3.3.3, ROADMAP task 3).** The registry is the single source of
truth for the ACTIONS, not only for the sequences that happened to exist in v1.3.1.1:
EVERY global action of the menus/sidebar/palette has an entry here. An action whose
``default`` is ``""`` simply has NO hotkey out of the box — it behaves exactly as
before (the menu item exists, the keyboard cannot reach it) — but it becomes
ASSIGNABLE in the "Hotkeys" tab. This is what closes "the action exists but the
keyboard cannot reach it": the audit in ``tests/test_actions_keyboard.py`` requires
every global action to be registered (no orphans), and a new global action = one line
here + ``MainWindow._register_hotkey_target()`` at creation.

Storage — the ``hotkeys`` key of ``~/.sshmap/config.json`` (dict action_id → "Ctrl+K",
merge-write via ``i18n.save_config``; the key itself is optional). Rules:

* a missing action_id → the default sequence (which may be "" = no hotkey);
* an unknown action_id → ignored (a downgrade / a rename must not break the config);
* a broken value (not a string / an unparsable sequence) → the default + a log line;
* an empty string → the action's hotkey is DISABLED (the action itself stays available
  from the menu) — the documented way to turn a hotkey off.

Sequences are canonicalized through ``QKeySequence`` (PortableText): the stored form,
the dialog's form and the compared form are always the same string (``"Delete"`` and
``"Del"`` are one sequence).

**Scope boundary** (pinned in DOCUMENTATION.md): the terminal canvas's OWN keys
(F1–F12, Ctrl+C/D/Z, arrows — xterm protocol territory) are NOT configurable; they
belong to the wire protocol, not to the application's action map.
"""

from typing import Dict, List, Optional, Sequence

from PySide6.QtGui import QKeySequence, QShortcut

# ── The registry (declaration order = the order of the settings table's rows) ──────
# v1.3.3.3: 30 actions — the 18 of v1.3.2 (each with the sequence it had) + 4 NEW
# defaults (file.save_as Ctrl+Shift+S, view.reset_zoom Ctrl+0, view.zoom_in Ctrl+=,
# view.zoom_out Ctrl+-) + 8 more that had no shortcut and now have an EMPTY default
# (assignable, no behavior change). `test_actions_keyboard.py` keeps the count and the
# completeness honest.
HOTKEY_ACTIONS: Dict[str, dict] = {
    # File
    "file.new":             {"label": "file.new_project",    "default": "Ctrl+N"},
    "file.open":            {"label": "file.open",           "default": "Ctrl+O"},
    "file.save":            {"label": "file.save",           "default": "Ctrl+S"},
    # v1.3.3.3 (task 1): "Save As…" had no shortcut and no way to get one.
    "file.save_as":         {"label": "file.save_as",        "default": "Ctrl+Shift+S"},
    # Edit
    "edit.undo":            {"label": "edit.undo",           "default": "Ctrl+Z"},
    # Ctrl+Y — the legacy alias of redo (v0.8.3): it follows the default only.
    "edit.redo":            {"label": "edit.redo",           "default": "Ctrl+Shift+Z",
                             "alt": ("Ctrl+Y",)},
    "edit.add_server":      {"label": "edit.add_server",     "default": "Ctrl+Shift+A"},
    "edit.add_group":       {"label": "edit.add_group",      "default": "Ctrl+Shift+G"},
    "edit.add_connection":  {"label": "edit.add_connection", "default": "Ctrl+Shift+C"},
    "edit.properties":      {"label": "edit.properties",     "default": "Ctrl+I"},
    "edit.duplicate":       {"label": "edit.duplicate",      "default": "Ctrl+D"},
    "edit.delete":          {"label": "edit.delete",         "default": "Delete"},
    # The selected node (the v0.9.2 set)
    "node.ssh_connect":     {"label": "ctx.ssh_connect",     "default": "Ctrl+Return"},
    "node.edit_server":     {"label": "ctx.edit_server",     "default": "Ctrl+E"},
    "node.add_note":        {"label": "ctx.add_note",        "default": "Ctrl+Shift+N"},
    # v1.3.3.3 (task 5): the on-demand status round — the node context menu on the map
    # and in the sidebar; no hotkey by default.
    "node.check_status":    {"label": "ctx.check_status",    "default": ""},
    # View
    "view.fit_map":         {"label": "view.fit_map",        "default": "Ctrl+Shift+F"},
    "view.find_on_map":     {"label": "view.find_on_map",    "default": "Ctrl+F"},
    # v1.3.3.3 (task 2): zoom becomes a first-class action — a real step API on MapView.
    "view.reset_zoom":      {"label": "view.reset_zoom",     "default": "Ctrl+0"},
    "view.zoom_in":         {"label": "view.zoom_in",        "default": "Ctrl+="},
    "view.zoom_out":        {"label": "view.zoom_out",       "default": "Ctrl+-"},
    # The command palette (a QShortcut in MainWindow._setup_command_palette)
    "palette.open":         {"label": "palette.title",       "default": "Ctrl+K"},
    # v1.2.3: multi-input — installed ONLY while the mode is on (see _sync_multi_shortcut)
    "view.multi_input":     {"label": "view.multi_input",    "default": "F12",
                             "dynamic": True},
    # ── v1.3.3.3 (task 3): the remaining GLOBAL actions — EMPTY defaults ───────────
    # They have no hotkey out of the box (the behaviour is unchanged: the menu item
    # exists, the keyboard cannot reach it) but every one of them is assignable in the
    # "Hotkeys" tab. "Reset to defaults" clears exactly these fields.
    "file.import_servers":  {"label": "file.import_servers",  "default": ""},
    "file.export_png":      {"label": "file.export_png",      "default": ""},
    "file.export_drawio":   {"label": "file.export_drawio",   "default": ""},
    "file.export_pdf":      {"label": "file.export_pdf",      "default": ""},
    "file.export_svg":      {"label": "file.export_svg",      "default": ""},
    "file.backups":         {"label": "file.backups",         "default": ""},
    "file.restore_autosave": {"label": "file.restore_autosave", "default": ""},
    "file.exit":            {"label": "file.exit",            "default": ""},
    "edit.connect_selected": {"label": "edit.connect_selected", "default": ""},
    "edit.delete_selected": {"label": "edit.delete_selected", "default": ""},
    "view.center_map":      {"label": "view.center_map",      "default": ""},
    "view.collapse_all":    {"label": "view.collapse_all",    "default": ""},
    "view.expand_all":      {"label": "view.expand_all",      "default": ""},
    "view.set_background":  {"label": "view.set_background",  "default": ""},
    "view.remove_background": {"label": "view.remove_background", "default": ""},
    "profile.manage":       {"label": "profile.manage",       "default": ""},
    "help.open_logs":       {"label": "help.open_logs",       "default": ""},
    "help.about":           {"label": "about.open",           "default": ""},
}

# v1.3.3.3: the actions that ship WITHOUT a hotkey (an empty registry default).
EMPTY_DEFAULT_ACTIONS = tuple(aid for aid, spec in HOTKEY_ACTIONS.items()
                              if not str(spec.get("default", "")).strip())

CONFIG_KEY = "hotkeys"   # the ~/.sshmap/config.json key (merge-write)


def _canonical(text: str) -> str:
    """A sequence string → the canonical PortableText form ("" stays "")."""
    seq = QKeySequence(text)
    return seq.toString(QKeySequence.SequenceFormat.PortableText)


# The defaults, canonicalized once at import (``"Delete"`` → ``"Del"``).
_DEFAULTS: Dict[str, str] = {aid: _canonical(str(spec["default"]))
                             for aid, spec in HOTKEY_ACTIONS.items()}
_ALTS: Dict[str, tuple] = {aid: tuple(_canonical(a) for a in spec.get("alt", ()))
                           for aid, spec in HOTKEY_ACTIONS.items()}


def action_ids() -> List[str]:
    """All registry ids, in declaration order (the settings table's row order)."""
    return list(HOTKEY_ACTIONS)


def action_label_key(action_id: str) -> str:
    """The i18n key of the action's name (an existing menu key; "" for an unknown id)."""
    spec = HOTKEY_ACTIONS.get(action_id)
    return str(spec["label"]) if spec else ""


def default_sequence(action_id: str) -> str:
    """The registry default of the action (canonical; "" = no hotkey / unknown id)."""
    return _DEFAULTS.get(action_id, "")


def default_hotkeys() -> Dict[str, str]:
    """The FULL registry default mapping {action_id: sequence} (v1.3.3.3, task 4).

    The single source for the "Reset to defaults" button of the "Hotkeys" tab: it
    writes THIS mapping through the ordinary merge-write (``save_hotkeys``), so no
    default is duplicated in the dialog. An empty value is a real default (the action
    ships without a hotkey) — the mapping covers every registry id.
    """
    return {aid: default_sequence(aid) for aid in action_ids()}


def empty_default_action_ids() -> List[str]:
    """The ids whose registry default is empty = "no hotkey" (v1.3.3.3, task 3)."""
    return list(EMPTY_DEFAULT_ACTIONS)


def alt_sequences(action_id: str) -> tuple:
    """The legacy extra sequences (canonical); applied only while the default is in use."""
    return _ALTS.get(action_id, ())


def is_dynamic(action_id: str) -> bool:
    """True — the sequence is installed by the mode's own code, not by apply_to()."""
    return bool(HOTKEY_ACTIONS.get(action_id, {}).get("dynamic"))


def normalize(value) -> Optional[str]:
    """A config value → a canonical sequence, "" (disabled) or None (broken).

    None means "the value is unusable" — the caller falls back to the default.
    A broken value is: a non-string, or a string that QKeySequence cannot parse
    (Qt accepts ``"Ctrl+NotAKey"`` without an error — it just yields an empty text).
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return ""          # the documented "disabled" value
    seq = QKeySequence(text)
    if seq.isEmpty() or seq.count() == 0:
        return None
    canonical = seq.toString(QKeySequence.SequenceFormat.PortableText)
    return canonical or None


def sequences_for(action_id: str, value) -> List[str]:
    """The sequence list to install for the action: [] (disabled) | [seq] | [seq, alt…]."""
    norm = normalize(value)
    if norm is None:
        norm = default_sequence(action_id)
    if not norm:
        return []
    out = [norm]
    if norm == default_sequence(action_id):
        out.extend(alt_sequences(action_id))
    return out


def action_sequence(action_id: str, mapping: Optional[dict] = None) -> str:
    """The effective SINGLE sequence of the action ("" = disabled). Never raises."""
    value = (mapping or {}).get(action_id, default_sequence(action_id))
    norm = normalize(value)
    return default_sequence(action_id) if norm is None else norm


def configured_hotkeys() -> Dict[str, str]:
    """The EFFECTIVE mapping action_id → sequence (registry defaults + the saved config).

    Never raises: a missing / broken config or an i18n import failure yields the
    defaults (a broken startup is worse than a lost customization).
    """
    mapping = {aid: default_sequence(aid) for aid in action_ids()}
    try:
        from i18n import load_config
        stored = load_config().get(CONFIG_KEY)
    except Exception:  # noqa: BLE001 — without i18n there is no config at all
        stored = None
    if not isinstance(stored, dict):
        return mapping
    for aid, value in stored.items():
        if aid not in HOTKEY_ACTIONS:
            continue                      # an unknown id (another version) — ignored
        norm = normalize(value)
        if norm is None:
            _log(f"broken hotkey value for {aid!r}: {value!r} — the default is used")
            continue                      # broken → the default stays in the mapping
        mapping[aid] = norm
    return mapping


def save_hotkeys(mapping: dict) -> bool:
    """Write the mapping to ``hotkeys`` in config.json (atomic merge-write).

    Only registry ids are stored, every value is normalized/validated (a broken one
    becomes the default — the file never carries an unusable sequence). The other
    config keys are preserved by ``i18n.save_config``. Never raises.
    """
    clean: Dict[str, str] = {}
    for aid in action_ids():
        norm = normalize(mapping.get(aid, default_sequence(aid)))
        clean[aid] = default_sequence(aid) if norm is None else norm
    try:
        from i18n import save_config
        return bool(save_config({CONFIG_KEY: clean}))
    except Exception as e:  # noqa: BLE001 — saving must not break the dialog
        _log(f"save_hotkeys failed: {e!r}")
        return False


def find_conflicts(mapping: dict) -> set:
    """The ids of the actions that share a sequence with ANOTHER action.

    Empty sequences are never a conflict (a disabled hotkey collides with nothing);
    the legacy aliases count too (assigning Ctrl+Y to another action conflicts with
    redo while redo still carries its default).
    """
    seen: Dict[str, List[str]] = {}
    for aid in action_ids():
        for seq in sequences_for(aid, mapping.get(aid, default_sequence(aid))):
            seen.setdefault(seq, [])
            if aid not in seen[seq]:
                seen[seq].append(aid)
    conflicts = set()
    for ids in seen.values():
        if len(ids) > 1:
            conflicts.update(ids)
    return conflicts


def apply_to(targets: Dict[str, list], mapping: Optional[dict] = None) -> None:
    """Install the mapping into the registered targets ``{action_id: [QAction|QShortcut…]}``.

    Dynamic actions are SKIPPED (their mode owns the sequence). A dead C++ object
    (teardown race) is skipped silently — the registry must never break a shutdown.
    """
    effective = mapping if mapping is not None else configured_hotkeys()
    for aid, objects in targets.items():
        if is_dynamic(aid):
            continue
        seqs = sequences_for(aid, effective.get(aid, default_sequence(aid)))
        for obj in objects:
            _set_sequence(obj, seqs)


def _set_sequence(obj, seqs: Sequence[str]) -> None:
    """QAction.setShortcuts / QShortcut.setKey; [] = no shortcut (an empty QKeySequence)."""
    try:
        if isinstance(obj, QShortcut):
            obj.setKey(QKeySequence(seqs[0]) if seqs else QKeySequence())
        else:
            obj.setShortcuts([QKeySequence(s) for s in seqs])
    except RuntimeError:
        pass  # the C++ object is already destroyed (close race) — nothing to update


def _log(message: str) -> None:
    """A lazy logger (the module is imported very early — keep the import cost out)."""
    try:
        from modules.logger import get_logger
        get_logger("ui.hotkey_registry").warning(message)
    except Exception:  # noqa: BLE001 — logging must never break the config read
        pass
