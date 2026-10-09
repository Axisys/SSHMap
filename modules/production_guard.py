# -*- coding: utf-8 -*-
"""The production-tag guard — ONE policy, TWO verbs (v1.9).

A node's own `tags` decide whether a gesture that reaches MORE THAN ONE session, or that pushes a whole
BLOCK of text into one, must be confirmed first: the two verbs are the MULTI-INPUT broadcast and a
MULTI-LINE paste. The policy is `guard_tags` (+ the optional `guard_verbs`) of `~/.sshmap/config.json` —
CONFIG and never the project, so `VERSION_FORMAT` does not move and one user's guard is not carried into
a shared file — and its default is EMPTY: a policy that shipped ON would change the behaviour of every
existing map whose owner happens to use a tag called `prod`. `guard_tag()` / `verb_enabled()` /
`needs_confirmation()` / `node_tags()` are PURE (the topical test drives them without a window);
`confirm()` is the ONE dialog and reads the config through `i18n.load_config()`.
Rule and owner — `AGENTS.md` §4.28, mechanism — `DOCUMENTATION.md` §72.
"""

try:
    from PySide6.QtWidgets import QMessageBox
except ImportError:  # pragma: no cover — Qt is a hard dependency of the application
    QMessageBox = None

from i18n import load_config, t

GUARD_TAGS_KEY = "guard_tags"        # the tags that guard a node (a list of strings, default [])
GUARD_VERBS_KEY = "guard_verbs"      # which gestures ask (default: both)
VERB_BROADCAST = "broadcast"         # "Multi-input" — every keystroke to every other session
VERB_PASTE = "paste"                 # a MULTI-LINE clipboard paste into one session
GUARD_VERBS = (VERB_BROADCAST, VERB_PASTE)
MAX_GUARD_TAGS = 32                  # a policy, not a database


def _texts(value, limit=MAX_GUARD_TAGS):
    """One config value as a tuple of non-empty strings (a foreign type → `()`)."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return ()
    out = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return tuple(out[:limit])


def guard_tags(cfg=None) -> tuple:
    """The configured guard tags, in the user's order — `()` when none is named (the default)."""
    cfg = load_config() if cfg is None else cfg
    try:
        return _texts(cfg.get(GUARD_TAGS_KEY))
    except Exception:  # noqa: BLE001 — a broken store is "no policy"
        return ()


def guard_verbs(cfg=None) -> tuple:
    """The verbs the guard covers — BOTH unless `guard_verbs` narrows it to a known name."""
    cfg = load_config() if cfg is None else cfg
    try:
        chosen = tuple(v for v in _texts(cfg.get(GUARD_VERBS_KEY)) if v in GUARD_VERBS)
    except Exception:  # noqa: BLE001
        chosen = ()
    return chosen or GUARD_VERBS


def node_tags(node) -> list:
    """The `tags` of a node-like value (a `ServerData`, a `PluginNode`, a dict), defensively."""
    if node is None:
        return []
    if isinstance(node, dict):
        raw = node.get("tags")
    else:
        raw = getattr(node, "tags", None)
    return [str(item).strip() for item in (raw if isinstance(raw, (list, tuple)) else [])
            if str(item).strip()]


def guard_tag(tags, cfg=None) -> str:
    """The FIRST configured guard tag that `tags` carries — `""` when the node is not guarded."""
    wanted = [tag.lower() for tag in guard_tags(cfg)]
    if not wanted:
        return ""
    for tag in tags or ():
        text = str(tag or "").strip()
        if text and text.lower() in wanted:
            return text
    return ""


def verb_enabled(verb, cfg=None) -> bool:
    """Is this verb guarded at all? (both by default, `guard_verbs` may drop one)."""
    return verb in guard_verbs(cfg)


def needs_confirmation(verb, tags, cfg=None) -> str:
    """The tag that makes `verb` ask before it runs, `""` when the gesture may go ahead.

    The ONE decision both call sites ask; PURE, so the policy is testable without a window.
    """
    if not verb_enabled(verb, cfg):
        return ""
    return guard_tag(tags, cfg)


def confirmation_text(verb, tag, alias="", lines=0, names="") -> str:
    """The ONE sentence of the dialog, from the verb's own key (an author's string stays out)."""
    if verb == VERB_PASTE:
        who = str(alias or "").strip() or "?"
        return t("guard.paste", alias=who, tag=str(tag), lines=int(lines or 0))
    return t("guard.broadcast", names=str(names or tag or "?"))


def confirm(verb, tag, alias="", lines=0, names="", parent=None) -> bool:
    """The ONE dialog of the guard: True when the user confirmed the gesture.

    A `QMessageBox` with the two shipped buttons (Yes/No are Qt's own translations) and the module
    attribute `QMessageBox` as the test seam (`modules/command_library.py`'s pattern). A build that
    cannot show a dialog at all (no Qt) answers False — the guard is a REFUSAL by default, never a
    silent pass; a `parent=None` box is legal Qt and therefore still asked.
    """
    if QMessageBox is None:
        return False
    try:
        box = QMessageBox(parent)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(t("guard.title"))
        box.setText(confirmation_text(verb, tag, alias=alias, lines=lines, names=names))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes
    except Exception:  # noqa: BLE001 — a dialog that cannot open never green-lights a gesture
        return False
