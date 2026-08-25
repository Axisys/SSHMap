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
    # v0.8.4 (DESIGN.md §D): свёрнутая плашка — одна строка. Сохраняется через
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

    def __post_init__(self):
        if self.tags is None:
            self.tags = []


def server_data_from_dict(raw: dict) -> ServerData:
    """Собрать ServerData из сырого JSON-словаря.

    Неизвестные/лишние ключи игнорируются, типы приводятся в порядок.
    """
    import uuid

    fields = ServerData.__dataclass_fields__
    data = {k: v for k, v in raw.items() if k in fields}
    if not data.get('id'):  # id обязателен — генерируем, если в JSON его нет
        data['id'] = str(uuid.uuid4())[:8]
    # Дефолты как при ручной сборке ServerData в старых версиях _open_project()
    data.setdefault('alias', 'Server')
    data.setdefault('host', 'localhost')
    data.setdefault('user', 'ubuntu')
    data.setdefault('password', '')
    data.setdefault('key_path', '')
    try:
        data['ssh_port'] = int(data.get('ssh_port') or 22)
    except (TypeError, ValueError):
        data['ssh_port'] = 22
    for coord in ('x', 'y'):
        try:
            data[coord] = float(data.get(coord) or 0.0)
        except (TypeError, ValueError):
            data[coord] = 0.0
    # v0.8.4 (DESIGN.md §D): отсутствующий ключ → развёрнутый узел; приведение к bool
    # на случай повреждённого значения (0/1/строки из сторонних правок JSON).
    data['collapsed'] = bool(data.get('collapsed') or False)
    # v0.9: строковые поля автосбора — отсутствуют в старых JSON → пустая строка
    data.setdefault('os_name', '')
    data.setdefault('cpu_model', '')
    # v0.9.4: теги — отсутствуют в старых JSON → пустой список; приводим к list[str]
    raw_tags = data.get('tags')
    if not isinstance(raw_tags, (list, tuple)):
        raw_tags = [] if raw_tags in (None, "") else [str(raw_tags)]
    data['tags'] = [str(t).strip() for t in raw_tags if str(t).strip()]
    return ServerData(**data)


def server_data_to_dict(data: ServerData) -> dict:
    serialized = asdict(data)
    serialized.pop('password', None)  # пароль не храним в JSON
    return serialized
