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
    key_path: str = ""  # Путь к приватному ключу SSH
    x: float = 0.0
    y: float = 0.0
    cpu: str = ""
    ram: str = ""
    disk: str = ""
    ip: str = ""
    comment: str = ""
    ssh_port: int = 22  # SSH порт
    # v0.8.4 (бывш. DESIGN.md §D): свёрнутая плашка — одна строка. Сохраняется через
    # asdict(); старые проекты читаются развёрнутыми (server_data_from_dict дефолтит
    # отсутствующие ключи), а старые версии приложения новый ключ игнорируют.
    collapsed: bool = False
    # v0.9: автосбор данных о сервере (Linux). Заполняются вручную или
    # SystemInfoCollector'ом; хранятся в JSON (server_data_to_dict через asdict).
    os_name: str = ""     #PRETTY_NAME из /etc/os-release, напр. "Ubuntu 24.04 LTS"
    cpu_model: str = ""   # модель CPU из /proc/cpuinfo
    # v0.9.4: теги/роли окружений (prod/staging/dev/...). Список строк; хранится в
    # JSON как массив "tags" (server_data_to_dict через asdict). Backward-compat:
    # старые JSON без ключа читаются пустым списком (server_data_from_dict).
    tags: "list | None" = None
    # v1.0RC4: Быстрый запуск — список пунктов меню для сервера. Каждый пункт:
    # {"type": "url"|"command", "name": str, "value": str}. URL открывается в
    # браузере по умолчанию; command отправляется первой командой в SSH-терминал.
    # Хранится в JSON как массив "quick_launch" (asdict). Backward-compat: старые
    # JSON без ключа читаются пустым списком (server_data_from_dict), а старые
    # версии приложения неизвестный ключ просто игнорируют.
    quick_launch: "list | None" = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.quick_launch is None:
            self.quick_launch = []


def sanitize_quick_launch(raw) -> list:
    """v1.0RC4: привести сырое значение "quick_launch" к списку валидных пунктов.

    Пункт — dict {"type": "url"|"command", "name": str, "value": str}. Битые
    записи (не-dict, пустые name/value, неизвестный type) отбрасываются без
    падения загрузки — та же политика, что у tags/notes/groups.
    """
    out = []
    if isinstance(raw, (list, tuple)):
        for e in raw:
            if not isinstance(e, dict):
                continue
            # v1.0-fix (audit #3): явный null в JSON — e.get(...) вернёт None
            # (дефолт срабатывает только при ОТСУТСТВИИ ключа), и str(None) = "None"
            # проходил бы как валидное имя/значение. None → пустая строка → запись
            # отбрасывается, как и положено по политике «битые записи отбрасываются».
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
    """Собрать ServerData из сырого JSON-словаря.

    Неизвестные/лишние ключи игнорируются, типы приводятся в порядок.
    """
    import uuid

    fields = ServerData.__dataclass_fields__
    data = {k: v for k, v in raw.items() if k in fields}
    if not data.get('id'):  # id обязателен — генерируем, если в JSON его нет
        data['id'] = str(uuid.uuid4())[:8]
    # Дефолты как при ручной сборке ServerData в старых версиях _open_project().
    # v1.0-fix (audit #4): setdefault заполнял только ОТСУТСТВУЮЩИЕ ключи — явный
    # null в JSON ("host": null) проходил как None и крашил SSH-диалог на .strip()
    # (_start_worker). Теперь отсутствующий ключ И явный null дают дефолт; остальные
    # строковые поля — явный null → пустая строка (как отсутствующий ключ), чтобы
    # «битые» записи не роняли UI-пути, работающие с ServerData.
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
    # v0.8.4 (бывш. DESIGN.md §D): отсутствующий ключ → развёрнутый узел; приведение к bool
    # на случай повреждённого значения (0/1/строки из сторонних правок JSON).
    data['collapsed'] = bool(data.get('collapsed') or False)
    # v0.9.4: теги — отсутствуют в старых JSON → пустой список; приводим к list[str]
    raw_tags = data.get('tags')
    if not isinstance(raw_tags, (list, tuple)):
        raw_tags = [] if raw_tags in (None, "") else [str(raw_tags)]
    data['tags'] = [str(t).strip() for t in raw_tags if str(t).strip()]
    # v1.0RC4: Быстрый запуск — отсутствует в старых JSON → пустой список;
    # битые записи отбрасываются (sanitize_quick_launch)
    data['quick_launch'] = sanitize_quick_launch(data.get('quick_launch'))
    return ServerData(**data)


def server_data_to_dict(data: ServerData) -> dict:
    serialized = asdict(data)
    serialized.pop('password', None)  # пароль не храним в JSON
    return serialized
