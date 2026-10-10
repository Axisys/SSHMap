# -*- coding: utf-8 -*-
"""The ONE order of the server menu — the rows, their sections and the surface that offers them.

A card and a sidebar row describe the SAME server, so the two menus are declared ONCE here and read
by both: `graphics/map_view.py` renders the card menu and `ui/sidebar.py` the row menu. Each surface
adds only the rows it can offer (`CARD` / `SIDEBAR`), which is how a card-only verb stays DECLARED
instead of being levelled onto the other menu. Qt-free (names and tuples only), so either side may
import it. Mechanism — `DOCUMENTATION.md`, the context-menu section."""

#: The surfaces a row belongs to. `BOTH` is the ordinary case; the two others are the rows only
#: one menu can offer (a card can collapse and be duplicated, a sidebar row can be revealed).
BOTH = "both"
CARD = "card"
SIDEBAR = "sidebar"

#: A section boundary. The quick-launch row's OWN trailing separator belongs to its builder: only
#: a surface that really built that submenu may draw the line under it.
SEPARATOR = None

#: The key of the `Diagnostics ▸` submenu row (its children are `DIAGNOSTIC_ITEMS`).
DIAGNOSTICS_KEY = "diagnostics"

#: The four verbs that ASK the host something — the submenu's own order. They gate individually
#: (an unmanaged card refuses each with its own sentence), so the group is a section, not a rule.
DIAGNOSTIC_ITEMS = (
    ("ping", "ctx.ping"),
    ("check_status", "ctx.check_status"),
    ("diagnose", "ctx.diagnose_offline"),
    ("collect_info", "ctx.collect_info"),
)

#: The server menu, in the ONE order both surfaces render: `(key, i18n key, surface)` rows with
#: `SEPARATOR` between the sections. The diagnostic verbs sit in the `Diagnostics ▸` submenu.
#: The line UNDER Quick Launch is deliberately not here: only a surface that really built that
#: submenu may draw it, so its builder owns it (`_fill_quick_launch()` / the card's builder).
MENU_ITEMS = (
    ("quick_launch", "ctx.quick_launch", BOTH),
    ("ssh", "ctx.ssh_connect", BOTH),
    ("external", "ctx.ssh_external", BOTH),
    ("connect_to", "ctx.connect_to", BOTH),
    SEPARATOR,
    ("copy_ip", "ctx.copy_ip", BOTH),
    ("copy_hostname", "ctx.copy_hostname", BOTH),
    SEPARATOR,
    ("edit", "ctx.edit_server", BOTH),
    (DIAGNOSTICS_KEY, "ctx.diagnostics", BOTH),
    SEPARATOR,
    ("collapse", "ctx.collapse_server", CARD),
    ("reveal", "ctx.reveal_on_map", SIDEBAR),
    SEPARATOR,
    ("duplicate", "ctx.duplicate_server", CARD),
    ("delete", "ctx.delete_server", BOTH),
)


def rows(surface: str) -> tuple:
    """The declared rows of ONE surface: `(key, i18n key)` pairs and `SEPARATOR` markers.

    PURE — the surface is an argument, so the topical test can read the list each menu must render
    without a widget. An unknown surface answers the rows every surface carries (`BOTH`).
    """
    wanted = str(surface or BOTH)
    out = []
    for item in MENU_ITEMS:
        if item is SEPARATOR:
            out.append(SEPARATOR)
            continue
        key, i18n_key, surfaces = item
        if surfaces == BOTH or wanted == surfaces or wanted not in (CARD, SIDEBAR):
            out.append((key, i18n_key))
    return tuple(out)


def keys(surface: str) -> tuple:
    """The action keys of a surface, separators dropped (the `CONTEXT_MENU_ITEMS` reader)."""
    return tuple(key for key, _ in filter(None, rows(surface)))


def label_key(key: str) -> str:
    """The i18n key of ONE row ("" for an unknown or a separator row) — the PURE lookup."""
    for item in MENU_ITEMS:
        if item is not SEPARATOR and item[0] == str(key or ""):
            return item[1]
    return ""
