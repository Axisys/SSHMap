# -*- coding: utf-8 -*-
"""The DEMO MAP, built in code (AGENTS.md §4.19, DOCUMENTATION.md §43): the "open the example map"
of the empty state and of the Help menu, so a new user sees what the thing looks like.

`build_example_project()` is the whole API (plus `DEMO_STATUSES` / `demo_status_ids()`,
`unmanaged_example_ids()` and `is_reserved_host()`); the module is pure: no Qt, no file I/O, no config.

Four decisions: it is CODE, never a shipped data file (a factory cannot drift from the format, and
the suite checks it against the format itself); the addresses are RESERVED documentation ones
(RFC 5737), so a probe is honestly `offline` and nobody can scan a real host by accident; no status
is faked — an EMULATED status is always MARKED and never leaves the demo map (the "demo" badge, the
tooltip line and the SUPPRESSED age); "Save as" drops the emulation on purpose; the ONE unmanaged
neighbour is honest the same way, and the content is DATA while the tour (`example.note_text`) is TEXT."""

try:  # the format version — the single source of truth (never a literal here)
    from version import VERSION_FORMAT
except ImportError:  # package-style import
    from ..version import VERSION_FORMAT

# ── RFC 5737 (IPv4 documentation): 192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24 ──
# The demo uses the first block only; the constant is what the topical test measures
# the addresses against (and what the status line of the loaded map names).
RESERVED_NETWORK = "192.0.2.0/24"
RESERVED_PREFIX = "192.0.2."

# The ids are FIXED (not uuid4): the demo is deterministic, so the topical test can
# address a node by id and the "screenshot" of the map is stable between runs.
ROUTER = "e0000001"
WEB1 = "e0000002"
WEB2 = "e0000003"
DB1 = "e0000004"
K8S1 = "e0000005"
# v1.6.5 (ROADMAP task 6): the ONE UNMANAGED card of the demo — a neighbour this operator
# does NOT administer. It is the live sample of the release: it carries `unmanaged: True`,
# so no round ever probes it (the checker's skip set), it has no credentials, its menu has
# no SSH verbs and its band says so in words; the COMMENT is the only information such a
# card really has, which is exactly why the release keeps that line.
NEIGHBOUR = "e0000006"

WEB_GROUP = "e0000010"
TOUR_NOTE = "e0000020"

#: The comment of the unmanaged card — infrastructure DATA (English literal, like every alias
#: and host of this factory), not a UI string: the tour is `example.note_text`, the box's own
#: purpose is the user's own words.
NEIGHBOUR_COMMENT = "Branch firewall — vendor-managed, no login for us"

# ── the EMULATED statuses of the demo ────────────────────────────────────────────────
# The demo network does not exist, so a probe can only ever answer `offline`; the window
# paints THESE through the ordinary `ServerNode.set_status(status, emulated=True)` right
# after the load, and `demo_status_ids()` is the checker's skip set — `DOCUMENTATION.md`
# §43. NOTHING here is a project-format field: a status is never serialized.
DEMO_STATUSES = {
    ROUTER: "offline",
    WEB1: "online",
    WEB2: "warn",
    DB1: "online",
    K8S1: "offline",
}


def demo_status_ids() -> tuple:
    """The node ids of the demo whose status is EMULATED, in declaration order.

    `StatusChecker.set_skip_ids()` receives exactly this set while the example map is the
    open project — otherwise the first round would repaint an emulated card `offline`
    within seconds and the emulation would be a lie that lasts 30 s.
    """
    return tuple(DEMO_STATUSES)



def _t(key: str) -> str:
    """Safe i18n hook (the graphics/* and ui/empty_state.py pattern)."""
    try:
        from i18n import t as _translate
        return _translate(key)
    except Exception:  # noqa: BLE001 — a missing i18n must not break the factory
        return key


def is_reserved_host(host: str) -> bool:
    """True when `host` is an RFC 5737 documentation address (the demo's rule).

    Only the IPv4 documentation block the demo actually uses — a name is never
    "reserved" here, so `example.com`-style hosts would be caught by the topical
    test as a defect rather than silently accepted.
    """
    return str(host or "").strip().startswith(RESERVED_PREFIX)


def example_aliases() -> list:
    """The aliases of the demo's nodes, in map order (the test/README seam)."""
    return ["core-router", "web-01", "web-02", "db-01", "k8s-01", "neighbour-fw"]


def unmanaged_example_ids() -> tuple:
    """The ids of the demo's UNMANAGED cards (v1.6.5) — the release's live sample.

    One card, and it is deliberately NOT in `DEMO_STATUSES`: an unmanaged card has no
    status to declare either, because nothing measures it. The topical test addresses it by
    name through this seam instead of hard-coding the id twice.
    """
    return (NEIGHBOUR,)


def build_example_project() -> dict:
    """A small project dict in the ORDINARY format (see DOCUMENTATION.md §5).

    Six servers (five managed, ONE unmanaged neighbour), six connections — one of every
    connection type the map knows (`ssh`, `vpn`, `http`, `database`, `nfs`, `kubernetes`)
    — one group, one note and tags on every card. Every host is an RFC 5737 documentation
    address, so the probe round can only ever report the truth about a network that does
    not exist. The unmanaged card is connected to nothing: a device that is drawn on the
    diagram while nobody here holds a login for it is exactly what the v1.6.5 card is for.

    The returned dict carries NO key beyond the format: a load, a save and a
    `.drawio` export of it behave exactly like a user's own project, and the "this is
    an example" marker lives in the window (never in the file — a saved copy is the
    user's own project from that moment on).
    """
    servers = [
        # ── the edge of the demo network: the VPN gateway ──────────────────────
        {"id": ROUTER, "alias": "core-router", "host": "192.0.2.1", "user": "admin",
         "ip": "192.0.2.1", "x": -520.0, "y": 60.0,
         "os_name": "Debian 12", "cpu": "2 cores", "ram": "2 GB", "disk": "16 GB",
         "tags": ["network"]},
        # ── the web tier — the two cards inside the group ──────────────────────
        {"id": WEB1, "alias": "web-01", "host": "192.0.2.10", "user": "ubuntu",
         "ip": "192.0.2.10", "x": -300.0, "y": -170.0,
         "os_name": "Ubuntu 24.04 LTS", "cpu": "4 cores", "ram": "8 GB", "disk": "80 GB",
         "tags": ["prod", "web"],
         "quick_launch": [{"type": "url", "name": "Web UI",
                           "value": "http://192.0.2.10:8080/"}]},
        {"id": WEB2, "alias": "web-02", "host": "192.0.2.11", "user": "ubuntu",
         "ip": "192.0.2.11", "x": -60.0, "y": -170.0,
         "os_name": "Ubuntu 24.04 LTS", "cpu": "4 cores", "ram": "8 GB", "disk": "80 GB",
         "tags": ["prod", "web"]},
        # ── the data tier ─────────────────────────────────────────────────────
        {"id": DB1, "alias": "db-01", "host": "192.0.2.20", "user": "postgres",
         "ip": "192.0.2.20", "x": 200.0, "y": 60.0, "ssh_port": 2222,
         "os_name": "Rocky Linux 9", "cpu": "8 cores", "ram": "32 GB", "disk": "1 TB",
         "tags": ["prod", "db"]},
        # ── the cluster ───────────────────────────────────────────────────────
        {"id": K8S1, "alias": "k8s-01", "host": "192.0.2.30", "user": "kadmin",
         "ip": "192.0.2.30", "x": 420.0, "y": -170.0,
         "os_name": "Flatcar Container Linux", "cpu": "8 cores", "ram": "16 GB",
         "disk": "120 GB", "tags": ["k8s"]},
        # ── v1.6.5 (ROADMAP task 6): the NEIGHBOUR — documented, not administered ──
        # NO `user`, NO hardware and NO status: `unmanaged` closes the credential family,
        # the probe plan and the SSH verbs, and the card paints what it has (the address,
        # the comment and its tag chip) beside the "NO SSH" mark. `unmanaged_ping` stays
        # False — the opt-in is the user's decision, and the demo makes no network call.
        {"id": NEIGHBOUR, "alias": "neighbour-fw", "host": "192.0.2.40", "user": "",
         "ip": "192.0.2.40", "x": -180.0, "y": 60.0,
         "comment": NEIGHBOUR_COMMENT, "tags": ["network"],
         "unmanaged": True, "unmanaged_ping": False},
    ]

    # One connection of EVERY type — the demo is also the legend's live sample. The
    # labels are short operational notes (a port, a protocol), not translated text.
    connections = [
        {"source_id": ROUTER, "target_id": WEB1, "type": "vpn",
         "label": "VPN", "bidirectional": True},
        {"source_id": WEB1, "target_id": WEB2, "type": "ssh", "label": "mgmt"},
        {"source_id": WEB1, "target_id": DB1, "type": "http", "label": "API"},
        {"source_id": WEB2, "target_id": DB1, "type": "database", "label": "5432"},
        {"source_id": DB1, "target_id": K8S1, "type": "nfs", "label": "NFS"},
        {"source_id": K8S1, "target_id": WEB1, "type": "kubernetes", "label": "k8s API"},
    ]

    # Membership is GEOMETRIC (the format stores no member list): the frame below is
    # placed so that the centres of web-01/web-02 fall inside it AND the two cards sit
    # inside it with a margin (a card is 180–360 px wide — its real size depends on its
    # text, so the frame is measured against the built card by the topical test), while
    # the other three cards fall outside on BOTH axes.
    groups = [{"id": WEB_GROUP, "name": "Web tier",
               "x": -330.0, "y": -240.0, "width": 520.0, "height": 230.0}]

    notes = [{"id": TOUR_NOTE, "text": _t("example.note_text"),
              "x": -520.0, "y": 250.0, "width": 320.0, "height": 180.0}]

    return {
        "version": VERSION_FORMAT,   # the format is the loader's, not a copy of it
        "servers": servers,
        "connections": connections,
        "notes": notes,
        "groups": groups,
        "background": None,
        # The whole demo is framed from the first paint: the loader applies these to
        # the view (`MapView.set_zoom_and_center`) exactly as it does for a user file.
        "zoom": 0.85,
        "center_x": 60.0,
        "center_y": 80.0,
    }
