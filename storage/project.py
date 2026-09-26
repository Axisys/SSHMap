import json
import os
from typing import Dict, TYPE_CHECKING

try:
    from version import VERSION_FORMAT
except ImportError:
    from .version import VERSION_FORMAT

try:
    from ..models.server import server_data_to_dict
except ImportError:
    from models.server import server_data_to_dict

if TYPE_CHECKING:  # AUDIT v0.7.2 (low #16): annotation without a runtime circular import
    try:
        from ..graphics.server_node import ServerNode
    except ImportError:
        from graphics.server_node import ServerNode


def _log():
    """Lazy-imported logger — doesn't break the module if the logger is unavailable."""
    try:
        from modules.logger import get_logger
        return get_logger("storage.project")
    except Exception:
        return None


def load_project(path: str) -> dict:
    """Load a project from a JSON file."""
    log = _log()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = json.load(f)

        if log:
            server_count = len(raw.get('servers', []))
            conn_count = len(raw.get('connections', []))
            log.info("Project loaded", extra={"file": path, "servers": server_count, "connections": conn_count})

        return raw
    except (FileNotFoundError, json.JSONDecodeError) as e:
        if log:
            log.error(f"Failed to load project {path}: {e}")
        raise


def serialize_scene(
    nodes: "Dict[str, 'ServerNode']",  # quotes + TYPE_CHECKING — no runtime circular import (AUDIT v0.7.2 #16)
    arrows: list,
    zoom: float,
    center_x: float,
    center_y: float,
    notes=None,   # v0.7.2: a list of StickyNote (optional parameter)
    groups=None,  # v0.8.1: a list of NodeGroup — clusters/folders on the map ("groups" array)
    background=None,  # v0.9.1: BackgroundImage — the background image ("background" key)
) -> dict:
    """v0.9.7: scene → project JSON dict (single serializer).

    Common path for save_project() and autosave (storage/autosave.py):
    one format, no passwords in it (server_data_to_dict strips them).
    """
    servers = [server_data_to_dict(n.data) for n in nodes.values()]
    connections = []
    for a in arrows:
        conn = {
            'source_id': a.source.data.id,
            'target_id': a.target.data.id,
            'label': a.label_text,
            # v0.7: connection type (SSH/VPN/HTTP/Database/NFS/Kubernetes)
            'type': getattr(a, "connection_type", "ssh"),
        }
        # v1.2.6: bidirectional connection — optional field (the notes' server_id pattern):
        # written only when true; absent = unidirectional (old files without
        # the key are read as-is). VERSION_FORMAT "0.9" is unchanged.
        if getattr(a, "bidirectional", False):
            conn['bidirectional'] = True
        connections.append(conn)

    # v0.7.2: independent notes on the map (a separate array).
    # For old application versions the field is simply not read — backward-compat.
    notes_list = []
    for n in (notes or []):
        to_dict = getattr(n, "to_dict", None)
        if callable(to_dict):
            notes_list.append(to_dict())

    # v0.8.1: node groups (clusters/folders). Only geometry+name is stored —
    # membership is not serialized: the geometric invariant "node center in the top
    # group" recomputes it on load (MapScene.resync_group_members).
    groups_list = []
    for g in (groups or []):
        to_dict = getattr(g, "to_dict", None)
        if callable(to_dict):
            groups_list.append(to_dict())

    # v0.9.1: background image ({path, x, y, width, height}) or null.
    # The file is NOT embedded in the JSON; on load a missing path is ignored.
    background_dict = None
    if background is not None:
        to_dict = getattr(background, "to_dict", None)
        if callable(to_dict):
            background_dict = to_dict()

    return {
        # AUDIT v0.8.3 (#1): format version — from the centralized version.py
        # (VERSION_FORMAT changes only on a real schema change).
        # The field is not validated on load: 0.6/0.7/0.7.2/0.8.0 projects
        # are read without checking this string.
        'version': VERSION_FORMAT,
        'servers': servers,
        'connections': connections,
        'zoom': zoom,
        'center_x': float(center_x),
        'center_y': float(center_y),
        'notes': notes_list,
        'groups': groups_list,  # v0.8.1: [{id, name, x, y, width, height}, ...]
        'background': background_dict,  # v0.9.1: {path, x, y, width, height} | null
    }


def write_project_json(path: str, data: dict) -> None:
    """v0.9.7: atomic write of an already-serialized project (dict → file).

    Atomicity — the same as save_project had before v0.9.7 (tmp + fsync +
    os.replace, v0.9.3 fix): a crash mid-write doesn't corrupt the map file.
    A FAILED write removes the provisional file — the guard the rest of the
    writer family already carries, so no `<project>.json.tmp` is left next to
    the project (the error itself still propagates to the caller).
    """
    tmp_path = path + '.tmp'
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except OSError:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def save_project(
    path: str,
    nodes: "Dict[str, 'ServerNode']",  # quotes + TYPE_CHECKING — no runtime circular import (AUDIT v0.7.2 #16)
    arrows: list,
    zoom: float,
    center_x: float,
    center_y: float,
    notes=None,   # v0.7.2: a list of StickyNote (optional parameter)
    groups=None,  # v0.8.1: a list of NodeGroup — clusters/folders on the map ("groups" array)
    background=None,  # v0.9.1: BackgroundImage — the background image ("background" key)
):
    """Save the project to a JSON file (scene → serialize_scene → atomic write)."""
    log = _log()
    try:
        data = serialize_scene(
            nodes=nodes, arrows=arrows, zoom=zoom,
            center_x=center_x, center_y=center_y,
            notes=notes, groups=groups, background=background,
        )
        write_project_json(path, data)

        if log:
            log.info("Project saved", extra={
                "file": path,
                "servers": len(data.get('servers', [])),
                "connections": len(data.get('connections', [])),
                "notes": len(data.get('notes', [])),
                "groups": len(data.get('groups', [])),  # v0.8.1
            })
    except Exception:
        if log:
            log.exception(f"Failed to save project {path}")
        raise

