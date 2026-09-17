import json
from dataclasses import dataclass, asdict
from typing import Optional


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

    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.quick_launch is None:
            self.quick_launch = []


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
    # v0.9.4: tags — missing in old JSON → empty list; coerce to list[str]
    raw_tags = data.get('tags')
    if not isinstance(raw_tags, (list, tuple)):
        raw_tags = [] if raw_tags in (None, "") else [str(raw_tags)]
    data['tags'] = [str(t).strip() for t in raw_tags if str(t).strip()]
    # v1.0RC4: Quick launch — missing in old JSON → empty list;
    # corrupt records are dropped (sanitize_quick_launch)
    data['quick_launch'] = sanitize_quick_launch(data.get('quick_launch'))
    return ServerData(**data)


def server_data_to_dict(data: ServerData) -> dict:
    serialized = asdict(data)
    serialized.pop('password', None)  # the password is not stored in JSON
    return serialized
