# -*- coding: utf-8 -*-
"""v1.6.8 (ROADMAP task 4): the ATTENTION report — "what needs a look" as a table.

The third DATA report of the application, next to the inventory table of the LIST mode
(`ui/sidebar.list_report_rows()`) and the CONNECTION report (`storage/export_connections.py`).
The map already DECLARES which cards need attention — `graphics.node_group.is_in_trouble()`
is the predicate the group aggregate and the "problems only" lens share — but that SET
had no way out of the application: the lens dims the CANVAS, and the inventory report
leaves with whatever the search and the tag filter kept. This module answers the question
a dimmed map cannot be pasted into a ticket: give me the servers that are not fine, with
WHY each of them is on the list.

**The writer is NOT here on purpose** (the connection report's rule, literally): the
RFC-4180 quoting lives in ONE place — `ui/sidebar.list_table_text()` — and this module only
produces ROWS for it: the columns are declared once (`PROBLEM_COLUMNS`) and
`problem_report_rows()` builds the header plus one row per card in trouble.

**The predicate is IMPORTED, never restated.** `problem_nodes()` calls
`is_in_trouble(status, stale)` for every node, so the report, the group aggregate and the
lens can never disagree about who is on the list; the `stale` argument is the card's own
mark (`ServerNode.is_stale`), exactly the value the lens reads.

**An UNMANAGED card is never a problem.** It is never probed (`AGENTS.md` §4.21), so it
carries no status and no stale mark — and `is_in_trouble("", False)` answers False. That
falls out of the predicate rather than being a special case here, which is the point.

The header cells are TRANSLATED (the caller hands its translator in, the
`node_group.status_caption()` precedent) — a report is read by a human, and a language
switch moves it with the rest of the window.
"""
from typing import List

try:  # the ONE predicate of "needs attention" (v1.5.4) — imported, never restated
    from ..graphics.node_group import PROBLEM_STATUSES, STATUS_SEVERITY, is_in_trouble
except ImportError:  # flat layout: the project root itself is on sys.path
    from graphics.node_group import PROBLEM_STATUSES, STATUS_SEVERITY, is_in_trouble

#: (field id, i18n key) — the column order of the report, declared ONCE. It is the
#: report's OWN list: the inventory's `LIST_COLUMNS` is a different subject (every
#: server and its parameters), so the two share the writer and nothing else.
PROBLEM_COLUMNS = (
    ("alias", "report.problems.alias"),
    ("host", "report.problems.host"),
    ("status", "report.problems.status"),
    ("reason", "report.problems.reason"),
    ("checked", "report.problems.checked"),
)

#: The stale half of the vocabulary. The status half is NOT a new word: it is the
#: existing `legend.status.*` family, the only spelling of online/warn/offline.
STALE_KEY = "report.problems.stale"


def _translate_default(key: str, **kw) -> str:
    """The module's own i18n hook (the key itself when i18n is unavailable)."""
    try:
        from i18n import t as _t
        return _t(key, **kw)
    except Exception:
        try:
            return str(key).format(**kw)
        except (KeyError, IndexError, ValueError):
            return str(key)


def problem_reason(status, stale, translate=None) -> str:
    """WHY this card is on the list — the predicate's own vocabulary, in ONE place.

    The parts, in order: the status WORD when the status itself is a problem
    (`legend.status.warn` / `legend.status.offline` — the existing keys, so the report
    and the legend cannot spell a status two ways) and the STALE mark when the datum has
    grown old. A green-but-stale card therefore reads "stale" and nothing else: "Online"
    is not a reason to look, and the stale fact is. The two are joined by the same ` · `
    the group aggregate's caption uses (one separator for the application's compositions).
    """
    t = translate if callable(translate) else _translate_default
    parts: List[str] = []
    text = str(status or "")
    if text in PROBLEM_STATUSES:
        parts.append(t(f"legend.status.{text}"))
    if stale:
        parts.append(t(STALE_KEY))
    return " \u00b7 ".join(parts)


def problem_record(node, translate=None) -> dict:
    """The raw values of ONE card — the report's model, read from the live node.

    A duck-typed node (the topical test's stand-in) is welcome: everything is read
    defensively, and a missing piece yields an empty cell rather than an exception — a
    report must never be the thing that breaks on a half-torn scene.
    """
    data = getattr(node, "data", None)
    status = str(getattr(node, "status", "") or "")
    stale = bool(getattr(node, "is_stale", False))

    def _text(field: str) -> str:
        value = getattr(data, field, "") if data is not None else ""
        return str(value or "").strip()

    checked = ""
    freshness = getattr(node, "freshness_text", None)
    if callable(freshness):
        try:
            checked = str(freshness() or "")
        except Exception:  # noqa: BLE001 — a half-torn card must not break the report
            checked = ""
    return {
        "alias": _text("alias"),
        "host": _text("host"),
        "status": status,
        "stale": stale,
        "reason": problem_reason(status, stale, translate),
        "checked": checked,
    }


def problem_nodes(nodes) -> List:
    """The cards of ``nodes`` that need attention, in the order they were handed in.

    The ONE filter: `graphics.node_group.is_in_trouble()` over the card's status and its
    stale mark. It is the SAME call the "problems only" lens makes
    (`MainWindow._trouble_nodes()`), so the report and the dimmed map always hold the
    same set — and an unchecked or unmanaged card (no status, no stale mark) is in
    neither of them.
    """
    return [n for n in (nodes or ())
            if is_in_trouble(str(getattr(n, "status", "") or ""),
                             bool(getattr(n, "is_stale", False)))]


def problem_headers(translate=None) -> List[str]:
    """The header row of the report — the translated captions of `PROBLEM_COLUMNS`."""
    t = translate if callable(translate) else _translate_default
    return [t(key) for _field, key in PROBLEM_COLUMNS]


def problem_row(record: dict, translate=None) -> List[str]:
    """ONE card as the cells of `PROBLEM_COLUMNS` (a MISSING field is an empty cell)."""
    t = translate if callable(translate) else _translate_default
    record = record or {}
    cells: List[str] = []
    for field, _key in PROBLEM_COLUMNS:
        if field == "status":
            text = str(record.get("status") or "")
            # The status WORD is the existing legend key; a status with no declared word
            # stays as the datum itself rather than inventing a fourth spelling.
            cells.append(t(f"legend.status.{text}") if text in STATUS_SEVERITY
                         else text)
        elif field == "reason":
            cells.append(str(record.get("reason")
                             or problem_reason(record.get("status"),
                                               record.get("stale"), t)))
        else:
            cells.append(str(record.get(field) or ""))
    return cells


def problem_report_rows(nodes, translate=None) -> List[List[str]]:
    """The WHOLE report — the header FIRST, then one row per card in trouble.

    ``[]`` when nothing needs attention: the caller reports "all clear" instead of
    writing a file with a header and nothing under it (the `connection_report_rows()`
    rule), and an empty MAP takes the same path — the caller tells the two apart by
    asking the scene, not by parsing this answer.
    """
    trouble = problem_nodes(nodes)
    if not trouble:
        return []
    rows = [problem_headers(translate)]
    for node in trouble:
        rows.append(problem_row(problem_record(node, translate), translate))
    return rows


def problem_report_text(nodes, delimiter: str = ",", translate=None) -> str:
    """The report as CSV/TSV text — the SAME `list_table_text()` writer the other two use.

    Kept here (and not in the window) so the topical gate can measure the quoting of an
    alias or a host without a window: the writer is imported from `ui/sidebar.py`, never
    copied, which is what "no second copy of it" means literally.
    """
    try:
        from ..ui.sidebar import list_table_text
    except ImportError:
        try:
            from ui.sidebar import list_table_text
        except ImportError:  # flat layout: the ui/ directory itself is on sys.path
            from sidebar import list_table_text
    return list_table_text(problem_report_rows(nodes, translate), delimiter)
