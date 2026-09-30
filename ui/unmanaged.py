# -*- coding: utf-8 -*-
"""The ONE gate of an UNMANAGED card (AGENTS.md §4.21; DOCUMENTATION.md §55).

A card the user does not administer carries `ServerData.unmanaged` — the whole predicate
(`models.server.is_unmanaged`) — and this module says WHICH verbs it refuses and WHAT the refused row
says. The map's context menu, the sidebar's, the command palette, the Edit menu and every programmatic
entry point ask THIS table, so a verb can never be blocked in one surface and forgotten in another.
The gate is keyed by an ACTION ID and names: `ssh` (the terminal and the SFTP tab — one transport),
`external`, `collect_info`, `check_status`, `diagnose`, `ping` (refused UNLESS the card opted in)
and `ql_command` (a quick-launch COMMAND — a URL still opens, the browser needs no shell).
Everything else stays untouched (copying the IP/hostname, revealing, duplicating, groups, tags, notes,
the search, every export). A refusal is never silence: a gated row is DISABLED with its own sentence
(`unmanaged.blocked`, `{action}` = the row's label); a gated programmatic call writes `status.unmanaged_blocked`."""

try:  # the model — the ONE predicate of the release
    from ..models.server import is_unmanaged, unmanaged_ping_allowed
except ImportError:  # flat launch from the project root
    from models.server import is_unmanaged, unmanaged_ping_allowed

#: The verbs a managed-only card cannot serve, in the order the plan names them.
BLOCKED_ACTIONS = ("ssh", "external", "collect_info", "check_status", "diagnose",
                   "ql_command")

#: The ONE conditional member: ICMP is granted per card by `ServerData.unmanaged_ping`.
CONDITIONAL_ACTION = "ping"

#: EVERY action id the gate knows (the topical test pins the set, so a new verb cannot be
#: added to a menu without joining this table).
GATED_ACTIONS = frozenset(BLOCKED_ACTIONS + (CONDITIONAL_ACTION,))

#: The sidebars' `CONTEXT_MENU_ITEMS` action keys are the gate's OWN ids for six of the
#: seven rows, so a menu builder passes its key straight through; the two menus that do not
#: use keys at all (the map's `build_context_menu` and the palette's registry walk) pass the
#: ids of the table above and of `REGISTRY_ACTION_IDS`.

#: The registry action ids of the Edit menu (and therefore of the command palette) → the
#: gate's action ids. Only these four are permanent QActions with a hotkey target; the
#: external terminal, the terminal/SFTP family and the quick-launch commands are reached
#: through a context menu or a dialog, so they are gated where they are built.
REGISTRY_ACTION_IDS = {
    "node.ssh_connect": "ssh",
    "node.collect_info": "collect_info",
    "node.check_status": "check_status",
    "node.diagnose": "diagnose",
}

#: The i18n key of the templated refusal sentence (`{action}` = the row's own label) and
#: the one the status bar uses for a programmatic refusal.
REFUSAL_KEY = "unmanaged.blocked"
STATUS_REFUSAL_KEY = "status.unmanaged_blocked"


def resolve_action(action: str) -> str:
    """The gate's action id for a menu/registry key ("" — the gate does not know it)."""
    key = str(action or "")
    return key if key in GATED_ACTIONS else ""


def action_blocked(action: str, target) -> bool:
    """Does the gate REFUSE this action for this card? (PURE)

    `target` is a `ServerNode` or a bare `ServerData`. An unknown action id answers False —
    the gate only ever refuses what it declares, so a new menu row is unrestricted until it
    joins `GATED_ACTIONS` on purpose.
    """
    key = resolve_action(action)
    if not key:
        return False
    if key == CONDITIONAL_ACTION:
        # The OPT-IN exception (task 5): ICMP is allowed on an unmanaged card ONLY when the
        # card itself asked for it; a managed card keeps the ordinary ping of any node.
        return is_unmanaged(target) and not unmanaged_ping_allowed(target)
    return is_unmanaged(target)


def blocked_registry_action(action_id: str, target) -> bool:
    """Does the gate refuse the registry action behind this id? (the palette's question)"""
    return action_blocked(REGISTRY_ACTION_IDS.get(str(action_id or ""), ""), target)


def refusal_text(translate, action_label: str) -> str:
    """The sentence of a refused row: the row's OWN label inside the declared template.

    `translate` is the caller's `t` (the `module + callbacks` pattern — this module owns no
    translator). An unavailable i18n answers the key, which is what the fallback rule of
    §4.5 asks of a module that is not sure i18n exists.
    """
    label = str(action_label or "")
    try:
        return translate(REFUSAL_KEY, action=label)
    except Exception:  # noqa: BLE001 — a missing translator must not break a menu
        return REFUSAL_KEY


def gate_row(act, action: str, target, label: str, translate) -> bool:
    """DISABLE a menu row the gate refuses and give it the reason (True — it was gated).

    Duck-typed on purpose (`setEnabled` / `setToolTip`, no Qt import): the map's and the
    sidebar's menu builders share this ONE call, and the topical test drives it with a
    two-attribute stub. A row that is NOT gated is left exactly as it was built.
    """
    if act is None or not action_blocked(action, target):
        return False
    try:
        act.setEnabled(False)
        act.setToolTip(refusal_text(translate, label))
    except (AttributeError, RuntimeError):
        pass  # a stub / a Qt object removed during teardown — the row stays as it is
    return True
