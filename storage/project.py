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

if TYPE_CHECKING:  # AUDIT v0.7.2 (низкая #16): аннотация без runtime-циркулярного импорта
    try:
        from ..graphics.server_node import ServerNode
    except ImportError:
        from graphics.server_node import ServerNode


def _log():
    """Lazy-imported logger — не роняет модуль, если логгер недоступен."""
    try:
        from modules.logger import get_logger
        return get_logger("storage.project")
    except Exception:
        return None


def load_project(path: str) -> dict:
    """Загрузить проект из JSON-файла."""
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
    nodes: "Dict[str, 'ServerNode']",  # кавычки + TYPE_CHECKING — без runtime-циркуляра (AUDIT v0.7.2 #16)
    arrows: list,
    zoom: float,
    center_x: float,
    center_y: float,
    notes=None,   # v0.7.2: список StickyNote (необязательный параметр)
    groups=None,  # v0.8.1: список NodeGroup — кластеры/папки на карте (массив "groups")
    background=None,  # v0.9.1: BackgroundImage — фон-изображение (ключ "background")
) -> dict:
    """v0.9.7: сцена → dict проекта JSON (единый сериализатор).

    Общий путь для save_project() и автосохранения (storage/autosave.py):
    формат один, паролей в нём нет (server_data_to_dict их вырезает).
    """
    servers = [server_data_to_dict(n.data) for n in nodes.values()]
    connections = []
    for a in arrows:
        connections.append({
            'source_id': a.source.data.id,
            'target_id': a.target.data.id,
            'label': a.label_text,
            # v0.7: тип связи (SSH/VPN/HTTP/Database/NFS/Kubernetes)
            'type': getattr(a, "connection_type", "ssh"),
        })

    # v0.7.2: независимые заметки на карте (отдельный массив).
    # Для старых версий приложения поле просто не читается — backward-compat.
    notes_list = []
    for n in (notes or []):
        to_dict = getattr(n, "to_dict", None)
        if callable(to_dict):
            notes_list.append(to_dict())

    # v0.8.1: группы узлов (кластеры/папки). Хранится только геометрия+имя —
    # членство не сериализуется: геометрический инвариант «центр узла в верхней
    # группе» пересчитывает его при загрузке (MapScene.resync_group_members).
    groups_list = []
    for g in (groups or []):
        to_dict = getattr(g, "to_dict", None)
        if callable(to_dict):
            groups_list.append(to_dict())

    # v0.9.1: фоновое изображение ({path, x, y, width, height}) или null.
    # Файл НЕ встраивается в JSON; при загрузке отсутствующий путь игнорируется.
    background_dict = None
    if background is not None:
        to_dict = getattr(background, "to_dict", None)
        if callable(to_dict):
            background_dict = to_dict()

    return {
        # AUDIT v0.8.3 (#1): версия формата — из централизованного version.py
        # (VERSION_FORMAT меняется только при реальном изменении схемы).
        # Поле не валидируется при загрузке: проекты 0.6/0.7/0.7.2/0.8.0
        # читаются без проверки этой строки.
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
    """v0.9.7: атомарная запись уже сериализованного проекта (dict → файл).

    Атомарность — та же, что была в save_project до v0.9.7 (tmp + fsync +
    os.replace, v0.9.3 fix): крах посреди записи не рвёт файл с картой.
    """
    tmp_path = path + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def save_project(
    path: str,
    nodes: "Dict[str, 'ServerNode']",  # кавычки + TYPE_CHECKING — без runtime-циркуляра (AUDIT v0.7.2 #16)
    arrows: list,
    zoom: float,
    center_x: float,
    center_y: float,
    notes=None,   # v0.7.2: список StickyNote (необязательный параметр)
    groups=None,  # v0.8.1: список NodeGroup — кластеры/папки на карте (массив "groups")
    background=None,  # v0.9.1: BackgroundImage — фон-изображение (ключ "background")
):
    """Сохранить проект в JSON-файл (сцена → serialize_scene → атомарная запись)."""
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
    except Exception as e:
        if log:
            log.exception(f"Failed to save project {path}")
        raise

