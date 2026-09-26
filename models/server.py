from dataclasses import dataclass, asdict


@dataclass
class ServerData:
    id: str
    alias: str
    host: str
    user: str
    password: str = ""
    key_path: str = ""  # path to the SSH private key
    x: float = 0.0
    y: float = 0.0
    cpu: str = ""
    ram: str = ""
    disk: str = ""
    ip: str = ""
    comment: str = ""
    ssh_port: int = 22  # SSH port
    # v0.8.4 (former DESIGN.md §D): collapsed card — a single row. Saved via
    # asdict(); old projects are read as expanded (server_data_from_dict defaults
    # missing keys), and old application versions ignore the new key.
    collapsed: bool = False
    # v0.9: auto-collected server data (Linux). Filled in manually or
    # by SystemInfoCollector; stored in JSON (server_data_to_dict via asdict).
    os_name: str = ""     #PRETTY_NAME from /etc/os-release, e.g. "Ubuntu 24.04 LTS"
    cpu_model: str = ""   # CPU model from /proc/cpuinfo
    # v0.9.4: tags/environment roles (prod/staging/dev/...). A list of strings; stored in
    # JSON as the "tags" array (server_data_to_dict via asdict). Backward-compat:
    # old JSON without the key is read as an empty list (server_data_from_dict).
    tags: "list | None" = None
    # v1.0RC4: Quick launch — a list of menu entries for the server. Each entry:
    # {"type": "url"|"command", "name": str, "value": str}. URL opens in the
    # default browser; command is sent as the first command to the SSH terminal.
    # Stored in JSON as the "quick_launch" array (asdict). Backward-compat: old
    # JSON without the key is read as an empty list (server_data_from_dict), and old
    # application versions simply ignore the unknown key.
    quick_launch: "list | None" = None
    # v1.5.3 (ROADMAP task 1): WHEN the auto-collected facts above (os_name / cpu_model /
    # cpu / ram / disk / ip) were collected — epoch seconds, 0.0 = "not dated" (never
    # collected, or a project file written before this release). Optional and additive:
    # a missing key loads as 0.0 and the card stays unmarked (the tags/quick_launch
    # compatibility policy — write only when set, absent means the default, an old
    # application version ignores the unknown key). It is written WITH the values (ONE
    # write in `MainWindow._apply_info_result`), so a fact and its date can never drift:
    # the date is the age of THAT measurement, not of the file.
    # VERSION_FORMAT stays "0.9": an optional field with a default is not a schema change
    # (the `collapsed` / `tags` / `quick_launch` precedent).
    info_collected_at: float = 0.0
    # v1.6.5 (ROADMAP task 1): the NEIGHBOUR on the map — a card for a server this user
    # does NOT administer. The flag is the ONE predicate of the whole release: the card
    # carries no credentials (user / password / key_path / ssh_port are cleared and the
    # keyring is never written for it), no SSH verb reaches it, no probe round ever touches
    # it and it is painted with an honest "not monitored" mark instead of a status. Written
    # through `asdict()` like `collapsed`, so an old project loads as fully managed and an
    # older application version simply ignores the unknown key.
    unmanaged: bool = False
    # v1.6.5 (ROADMAP task 5): the OPT-IN reachability check of such a card — one ICMP
    # ping, on request, never a TCP/SSH probe. DEFAULT OFF: with it off no network call is
    # ever made for the card. Per-NODE data (the `collapsed` precedent) — deliberately NOT
    # a `config.json` key, so the settings hub's `collect()` does not move.
    unmanaged_ping: bool = False
    # v1.6.6 (ROADMAP task 5): the DATA MOUNT beside the root. A server whose capacity lives on
    # a separate volume reports the root's small number in `disk` while the filesystem that
    # really holds the data stays invisible; these four optional strings are the fix. They are
    # the only fields of the pair family and each one has its OWN job:
    #   disk_mount — the REQUEST: the path to measure ("" ⇒ the declared default `/opt`);
    #   disk_path  — the ANSWER: the mount point `df` really reported (`/` when the requested
    #                path has no filesystem of its own). Separate from the request ON PURPOSE:
    #                collapsing them would make a symlinked or automounted path indistinguishable
    #                from the typed one;
    #   disk_free  — the free figure of that mount;
    #   disk_size  — the capacity of that mount.
    # Additive optional strings, the `tags` / `info_collected_at` compatibility policy: a
    # missing key, an explicit null, a number or any foreign value loads as "" ("never
    # measured"), an older build ignores the keys, and `VERSION_FORMAT` stays "0.9" — an
    # optional field with a default is not a schema change.
    disk_mount: str = ""
    disk_path: str = ""
    disk_free: str = ""
    disk_size: str = ""

    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.quick_launch is None:
            self.quick_launch = []


def is_unmanaged(target) -> bool:
    """Is this card an UNMANAGED one — a server this user does not administer? (v1.6.5)

    The ONE predicate of the release (ROADMAP task 4): every SSH verb, the info
    collection, the status round, the reachability report and the quick-launch
    `command` entries ask THIS question, so a single flag can never be honoured in one
    place and forgotten in another. PURE and duck-typed: a `ServerNode` (which carries
    `.data`) and a bare `ServerData` both answer, and anything else answers False.
    """
    return bool(getattr(getattr(target, "data", target), "unmanaged", False))


def unmanaged_ping_allowed(target) -> bool:
    """May an unmanaged card be pinged on request? (v1.6.5, ROADMAP task 5)

    The OPT-IN half of the flag, and the SECOND question of the gate: `is_unmanaged()`
    refuses an action, this one asks whether the ONE exception the release grants — a
    reachability check that is pure ICMP, never a TCP/SSH probe — was switched on for
    this card. DEFAULT OFF, so a new unmanaged card makes no network call at all.
    """
    return bool(getattr(getattr(target, "data", target), "unmanaged_ping", False))


def info_collected_epoch(value) -> float:
    """Coerce a raw "info_collected_at" value into epoch seconds (v1.5.3, ROADMAP task 1).

    PURE, and the ONE place that decides what a usable timestamp is: a missing key, an
    explicit null, a non-numeric string, a NaN / infinite number and a NEGATIVE epoch all
    mean "not dated" (0.0). A negative value is refused on purpose: an epoch before 1970
    cannot be a collection this application performed, and letting it through would paint
    a "collected 20 000 days ago" mark on a hand-edited file.
    """
    try:
        moment = float(value)
    except (TypeError, ValueError):
        return 0.0
    if moment != moment or moment in (float("inf"), float("-inf")):  # NaN / ±inf
        return 0.0
    return moment if moment > 0.0 else 0.0


def optional_text(value) -> str:
    """Coerce a raw optional STRING field into its usable value (v1.6.6, ROADMAP task 5).

    PURE, and the ONE rule of the DATA-mount family (`disk_mount` / `disk_path` / `disk_free` /
    `disk_size`): a string is taken STRIPPED, and every other value — a missing key (`None`), an
    explicit null, a number, a boolean, a list or a dict — answers `""` ("never measured"). A
    number is deliberately NOT stringified: these fields hold a mount point or a formatted
    figure, and a stray `22` silently becoming a mount path would be a lie about a measurement
    instead of a missing one.
    """
    if isinstance(value, str):
        return value.strip()
    return ""


def sanitize_quick_launch(raw) -> list:
    """v1.0RC4: coerce a raw "quick_launch" value into a list of valid entries.

    An entry — a dict {"type": "url"|"command", "name": str, "value": str}. Corrupt
    records (non-dict, empty name/value, unknown type) are dropped without
    breaking the load — the same policy as for tags/notes/groups.
    """
    out = []
    if isinstance(raw, (list, tuple)):
        for e in raw:
            if not isinstance(e, dict):
                continue
            # v1.0-fix (audit #3): an explicit null in JSON — e.get(...) returns None
            # (the default only kicks in when the key is ABSENT), and str(None) = "None"
            # would pass as a valid name/value. None → empty string → the record
            # is dropped, as the "corrupt records are dropped" policy dictates.
            etype = str(e.get("type") or "url").strip().lower()
            if etype not in ("url", "command"):
                etype = "url"
            name = e.get("name")
            value = e.get("value")
            name = "" if name is None else str(name).strip()
            value = "" if value is None else str(value).strip()
            if not name or not value:
                continue
            out.append({"type": etype, "name": name, "value": value})
    return out


def server_data_from_dict(raw: dict) -> ServerData:
    """Build a ServerData from a raw JSON dict.

    Unknown/extra keys are ignored, types are normalized.
    """
    import uuid

    fields = ServerData.__dataclass_fields__
    data = {k: v for k, v in raw.items() if k in fields}
    if not data.get('id'):  # id is required — generate one if missing from JSON
        data['id'] = str(uuid.uuid4())[:8]
    else:
        # v1.2.10rc2 (manual AUDIT #5e): an explicit "id": 123 (int) in JSON earlier passed
        # through as-is — below, id is used as a string/key everywhere (keyring service name,
        # undo commands, registries). We coerce to str after the emptiness check.
        data['id'] = str(data['id'])
    # Defaults as when building ServerData manually in old versions of _open_project().
    # v1.0-fix (audit #4): setdefault only filled MISSING keys — an explicit
    # null in JSON ("host": null) passed through as None and crashed the SSH dialog on .strip()
    # (_start_worker). Now a missing key AND an explicit null yield the default; the other
    # string fields — an explicit null → empty string (like a missing key), so that
    # "corrupt" records don't break the UI paths working with ServerData.
    for _field, _default in (('alias', 'Server'), ('host', 'localhost'),
                             ('user', 'ubuntu'), ('password', ''), ('key_path', ''),
                             ('cpu', ''), ('ram', ''), ('disk', ''), ('ip', ''),
                             ('comment', ''), ('os_name', ''), ('cpu_model', '')):
        if data.get(_field) is None:
            data[_field] = _default
    # v1.6.6 (ROADMAP task 5): the four DATA-mount strings are coerced by ONE rule — the
    # `disk_mount` precedent (`_optional_text()`): a missing key, an explicit null, a number, a
    # list or any other foreign value all degrade to "" ("never measured"), so a hand-edited
    # project file can never put a non-string into a field the card and the dialog render.
    for _field in ('disk_mount', 'disk_path', 'disk_free', 'disk_size'):
        data[_field] = optional_text(data.get(_field))
    try:
        data['ssh_port'] = int(data.get('ssh_port') or 22)
    except (TypeError, ValueError):
        data['ssh_port'] = 22
    for coord in ('x', 'y'):
        try:
            data[coord] = float(data.get(coord) or 0.0)
        except (TypeError, ValueError):
            data[coord] = 0.0
    # v0.8.4 (former DESIGN.md §D): missing key → expanded node; coercion to bool
    # in case of a corrupted value (0/1/strings from external JSON edits).
    data['collapsed'] = bool(data.get('collapsed') or False)
    # v1.6.5 (ROADMAP tasks 1/5): the two additive flags of the UNMANAGED card. A project
    # written before the release carries neither key, so it loads as a fully MANAGED map;
    # a hand-edited junk value is coerced by the same bool() rule as `collapsed`.
    data['unmanaged'] = bool(data.get('unmanaged') or False)
    data['unmanaged_ping'] = bool(data.get('unmanaged_ping') or False)
    # v0.9.4: tags — missing in old JSON → empty list; coerce to list[str]
    raw_tags = data.get('tags')
    if not isinstance(raw_tags, (list, tuple)):
        raw_tags = [] if raw_tags in (None, "") else [str(raw_tags)]
    data['tags'] = [str(t).strip() for t in raw_tags if str(t).strip()]
    # v1.0RC4: Quick launch — missing in old JSON → empty list;
    # corrupt records are dropped (sanitize_quick_launch)
    data['quick_launch'] = sanitize_quick_launch(data.get('quick_launch'))
    # v1.5.3 (ROADMAP task 1): the age of the collected facts — missing in old JSON (and in
    # a hand-edited file with junk) → 0.0 = "not dated": the card stays unmarked and the
    # project loads unchanged. The ONE coercion lives in info_collected_epoch().
    data['info_collected_at'] = info_collected_epoch(data.get('info_collected_at'))
    return ServerData(**data)


def server_data_to_dict(data: ServerData) -> dict:
    serialized = asdict(data)
    serialized.pop('password', None)  # the password is not stored in JSON
    # v1.5.3 (ROADMAP task 1): the collection date is written ONLY when the node really has
    # one ("write only when set, absent means default" — the project-format invariant), so a
    # map whose data was never collected keeps the byte-for-byte file it had before this
    # release and an undated card stays unmarked on the next load.
    if not info_collected_epoch(serialized.get('info_collected_at')):
        serialized.pop('info_collected_at', None)
    # v1.6.6 (ROADMAP task 5): the REQUEST is written like the collected fields it sits beside
    # (an empty `disk_mount` is the meaningful "use the declared default"), while the three
    # ANSWERS are MEASUREMENTS — nothing was measured ⇒ the key is ABSENT, so an ordinary map
    # keeps the file it had and a project written before the release is never "measured" by a
    # later save (the `info_collected_at` rule, applied to a string family).
    for _field in ('disk_path', 'disk_free', 'disk_size'):
        if not optional_text(serialized.get(_field)):
            serialized.pop(_field, None)
    return serialized
