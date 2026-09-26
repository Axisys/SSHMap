# -*- coding: utf-8 -*-
"""v1.6 (ROADMAP task 5): the CONNECTION report — "who talks to whom" as a table.

The second DATA report of the application, next to the inventory table of the LIST mode
(`ui/sidebar.list_report_rows()`). It answers the question a picture cannot be searched
for: give me every link of the map with its two endpoints, its declared type and its
direction — as a CSV/TSV a spreadsheet can sort.

**The writer is NOT here on purpose.** The RFC-4180 quoting (a doubled `"`, a field
quoted only when it must be) lives in ONE place — `ui/sidebar.list_table_text()` — and
this module only produces ROWS for it: the columns are declared once (`CONNECTION_COLUMNS`)
and `connection_report_rows()` builds the header plus one row per link. A label with a
comma, a quote or a line break therefore leaves the application exactly the way the
inventory's comment does.

The header cells are TRANSLATED (the caller hands its translator in, the
`node_group.status_caption()` precedent) — a report is read by a human, and a language
switch moves it with the rest of the window.
"""
from typing import List

#: (field id, i18n key) — the column order of the report, declared ONCE.
CONNECTION_COLUMNS = (
    ("source_alias", "report.conn.source_alias"),
    ("source_host", "report.conn.source_host"),
    ("target_alias", "report.conn.target_alias"),
    ("target_host", "report.conn.target_host"),
    ("type", "report.conn.type"),
    ("direction", "report.conn.direction"),
    ("bidirectional", "report.conn.bidirectional"),
    ("label", "report.conn.label"),
)

#: The two words of the "bidirectional" cell (a flag is still a sentence for a reader).
BIDIRECTIONAL_YES_KEY = "report.conn.yes"
BIDIRECTIONAL_NO_KEY = "report.conn.no"


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


def connection_record(arrow) -> dict:
    """The raw values of ONE link — the report's model, read from the live arrow.

    A duck-typed arrow (the topical test's stand-in) is welcome: everything is read
    defensively, and a missing endpoint yields an empty cell rather than an exception —
    a report must never be the thing that breaks on a half-torn scene.
    """
    source = getattr(arrow, "source", None)
    target = getattr(arrow, "target", None)
    src_data = getattr(source, "data", None)
    tgt_data = getattr(target, "data", None)

    def _text(data, field: str) -> str:
        value = getattr(data, field, "") if data is not None else ""
        return str(value or "").strip()

    return {
        "source_alias": _text(src_data, "alias"),
        "source_host": _text(src_data, "host"),
        "target_alias": _text(tgt_data, "alias"),
        "target_host": _text(tgt_data, "host"),
        "type": str(getattr(arrow, "connection_type", "") or ""),
        "bidirectional": bool(getattr(arrow, "bidirectional", False)),
        "label": str(getattr(arrow, "label_text", "") or ""),
    }


def connection_headers(translate=None) -> List[str]:
    """The header row of the report — the translated captions of `CONNECTION_COLUMNS`."""
    t = translate if callable(translate) else _translate_default
    return [t(key) for _field, key in CONNECTION_COLUMNS]


def connection_row(record: dict, translate=None) -> List[str]:
    """ONE link as the cells of `CONNECTION_COLUMNS` (a MISSING field is an empty cell)."""
    t = translate if callable(translate) else _translate_default
    record = record or {}
    cells: List[str] = []
    for field, _key in CONNECTION_COLUMNS:
        if field == "direction":
            source = str(record.get("source_alias") or record.get("source_host") or "")
            target = str(record.get("target_alias") or record.get("target_host") or "")
            cells.append(f"{source} \u2192 {target}")
        elif field == "bidirectional":
            cells.append(t(BIDIRECTIONAL_YES_KEY if record.get("bidirectional")
                           else BIDIRECTIONAL_NO_KEY))
        else:
            cells.append(str(record.get(field) or ""))
    return cells


def connection_report_rows(arrows, translate=None) -> List[List[str]]:
    """The WHOLE report — the header FIRST, then one row per link (the inventory's shape).

    ``[]`` when there is no link at all: the caller reports "nothing to export" instead of
    writing a file with a header and nothing under it (the `list_report_rows()` rule).
    """
    links = list(arrows or ())
    if not links:
        return []
    rows = [connection_headers(translate)]
    for arrow in links:
        rows.append(connection_row(connection_record(arrow), translate))
    return rows


def connection_report_text(arrows, delimiter: str = ",", translate=None) -> str:
    """The report as CSV/TSV text — the SAME `list_table_text()` writer the inventory uses.

    Kept here (and not in the window) so the topical gate can measure the quoting of a
    connection label without a window: the writer is imported from `ui/sidebar.py`, never
    copied, which is what "no second copy of it" means literally.
    """
    try:
        from ..ui.sidebar import list_table_text
    except ImportError:
        try:
            from ui.sidebar import list_table_text
        except ImportError:  # flat layout: the ui/ directory itself is on sys.path
            from sidebar import list_table_text
    return list_table_text(connection_report_rows(arrows, translate), delimiter)
