# -*- coding: utf-8 -*-
"""v0.9.7: автосохранение + кольцевой буфер бэкапов проекта (ROADMAP v0.9.7).

Цель — страховка от порчи JSON / случайной потери правок:

  * автосохранение — полная сериализация проекта (тот же формат, что save_project;
    паролей в нём НЕТ: server_data_to_dict их вырезает) пишется в
    ``~/.sshmap/autosave/<key>.json`` по таймеру (интервал из конфига, дефолт 60 c),
    только при dirty и только если открыт файл проекта;
  * бэкапы — кольцевой буфер N файлов (дефолт 10) в ``~/.sshmap/backups/``:
    при каждом ручном save ДОС этого файла версия «до сохранения» сдвигается в
    слот 001, более старые слоты уезжают на +1, переполнение за N удаляется;
  * восстановление — атомарная копия бэкапа/автосохранения обратно в файл проекта.

Раскладка (тот же корень ~/.sshmap, что config.json / known_hosts / логи):

    ~/.sshmap/autosave/<key>.json        — последнее автосохранение проекта
    ~/.sshmap/backups/<key>_001.json     — самый свежий бэкап (предыдущая версия файла)
    ...
    ~/.sshmap/backups/<key>_NNN.json     — самый старый сохраняемый бэкап

``<key>`` = sha1[:16] нормализованного абсолютного пути файла проекта: стабилен
между сессиями, различает файлы с одинаковым именем в разных каталогах.

Модуль без Qt-зависимостей — тестируется plain python / offscreen (паттерн
storage/project.py). Все функции «тихие»: повреждённый/отсутствующий файл не
роняет ни запуск, ни сохранение — возвращают None/[] или логируют.
"""
import hashlib
import json
import os
import shutil
from typing import Dict, List, Optional

# ── Пути и дефолты ────────────────────────────────────────────────────────────

_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".sshmap")
AUTOSAVE_DIR = os.path.join(_CONFIG_DIR, "autosave")
BACKUPS_DIR = os.path.join(_CONFIG_DIR, "backups")

# ROADMAP v0.9.7: интервал настраиваемый, дефолт ~60 c; кольцевой буфер N файлов,
# дефолт 10. Конфиг — существующий ~/.sshmap/config.json (load_config из i18n):
#   autosave_enabled       bool, дефолт True
#   autosave_interval_sec  int,  дефолт 60
#   backup_count           int,  дефолт 10
# Диалог настроек для этих ключей появится в v1.1 (ROADMAP).
DEFAULT_AUTOSAVE_ENABLED = True
DEFAULT_AUTOSAVE_INTERVAL_SEC = 60
DEFAULT_BACKUP_COUNT = 10

_MIN_INTERVAL_SEC = 5            # защита от опечаток «1» / «0» в конфиге
_MAX_INTERVAL_SEC = 24 * 3600    # и от «999999»
_MIN_BACKUPS = 1
_MAX_BACKUPS = 100


# ── Ключ проекта ──────────────────────────────────────────────────────────────

def project_key(project_path: str) -> str:
    """Стабильный ключ файла проекта: sha1[:16] нормализованного абсолютного пути.

    normcase — безразличие к регистру/разделителям на Windows; abspath —
    относительные и абсолютные записи одного и того же файла дают один ключ.
    """
    norm = os.path.normcase(os.path.abspath(project_path))
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def autosave_path_for(project_path: str) -> str:
    """Путь автосохранения для файла проекта."""
    return os.path.join(AUTOSAVE_DIR, project_key(project_path) + ".json")


def backup_path_for(project_path: str, slot: int) -> str:
    """Путь бэкапа в кольце. Слот 1 = самый свежий (версия файла до последнего save)."""
    return os.path.join(BACKUPS_DIR, f"{project_key(project_path)}_{slot:03d}.json")


# ── Настройки ─────────────────────────────────────────────────────────────────

def get_autosave_settings() -> Dict:
    """Читает настройки из ~/.sshmap/config.json (load_config i18n, никогда не падает).

    Возвращает {"enabled": bool, "interval_sec": int, "backup_count": int}.
    Значения вне разумных диапазонов клампятся; битые значения → дефолт.
    """
    cfg: dict = {}
    try:
        from i18n import load_config
        cfg = load_config() or {}
    except Exception:  # noqa: BLE001 — конфиг опционален, дефолты важнее
        pass

    def _int(value, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    enabled = bool(cfg.get("autosave_enabled", DEFAULT_AUTOSAVE_ENABLED))
    interval = max(_MIN_INTERVAL_SEC, min(
        _int(cfg.get("autosave_interval_sec"), DEFAULT_AUTOSAVE_INTERVAL_SEC),
        _MAX_INTERVAL_SEC))
    backups = max(_MIN_BACKUPS, min(
        _int(cfg.get("backup_count"), DEFAULT_BACKUP_COUNT),
        _MAX_BACKUPS))
    return {"enabled": enabled, "interval_sec": interval, "backup_count": backups}


# ── Атомарная запись (паттерн save_project / save_config) ────────────────────

def atomic_write_json(path: str, data: dict) -> None:
    """Атомарная запись JSON: tmp + fsync + os.replace.

    Крах/обрыв питания посреди записи не рвёт ни автосохранение, ни бэкап —
    replace либо происходит целиком, либо нет (v0.9.3 fix для save_project).
    """
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def read_json(path: str) -> Optional[dict]:
    """Прочитать JSON-dict; None при отсутствии/повреждении (тихо — см. docstring)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _atomic_copy(src: str, dst: str) -> None:
    """Атомарная копия файла: copy2 в tmp + os.replace.

    copy2 сохраняет mtime — для бэкапов это «когда была сделана версия»
    (колонка «Изменён» в диалоге бэкапов).
    """
    directory = os.path.dirname(dst)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp_path = dst + ".tmp"
    shutil.copy2(src, tmp_path)
    os.replace(tmp_path, dst)


# ── Автосохранение (ROADMAP v0.9.7 #1, #3) ───────────────────────────────────

def write_autosave(project_path: str, data: dict) -> str:
    """Записать последнее автосохранение проекта. Возвращает путь файла."""
    path = autosave_path_for(project_path)
    atomic_write_json(path, data)
    return path


def read_autosave(project_path: str) -> Optional[dict]:
    """Содержимое последнего автосохранения (None — отсутствует/повреждено)."""
    return read_json(autosave_path_for(project_path))


def autosave_mtime(project_path: str) -> Optional[float]:
    """mtime автосохранения (None, если файла нет)."""
    path = autosave_path_for(project_path)
    try:
        return os.path.getmtime(path) if os.path.isfile(path) else None
    except OSError:
        return None


def autosave_is_newer(project_path: str) -> bool:
    """ROADMAP v0.9.7 #3: автосохранение свежее файла на диске?

    Только сравнение mtime — «свежесть» определяется файловой системой,
    без доверия к содержимому (битое автосохранение read_autosave отклонит).
    """
    a = autosave_path_for(project_path)
    if not (os.path.isfile(a) and os.path.isfile(project_path)):
        return False
    try:
        return os.path.getmtime(a) > os.path.getmtime(project_path)
    except OSError:
        return False


# ── Кольцевой буфер бэкапов (ROADMAP v0.9.7 #2) ─────────────────────────────

def rotate_backups(project_path: str, max_count: int = DEFAULT_BACKUP_COUNT) -> List[str]:
    """Сдвинуть кольцевой буфер и положить текущий файл в слот 1.

    Вызывается ДО перезаписи файла проекта (из MainWindow._do_save): в слоты
    попадает версия «до сохранения» — откат на предыдущие версии файла.
    Слот i → i+1 (сдвиг идёт от старых к новым), переполнение за max_count
    удаляется (актуально, если backup_count в конфиге уменьшили).

    Возвращает список существующих слотов (свежие первыми). Файл проекта
    отсутствует (первое сохранение нового пути) → [] и молчание.
    """
    if not os.path.isfile(project_path):
        return []
    for slot in range(max_count, 1, -1):
        src = backup_path_for(project_path, slot - 1)
        if os.path.isfile(src):
            _atomic_copy(src, backup_path_for(project_path, slot))
    # Остатки за пределами нового max_count (уменьшение N в конфиге).
    # v1.0-fix (audit #5): сканируем до жёсткого лимита _MAX_BACKUPS, а не фиксированное
    # окно в 63 слота — раньше при уменьшении backup_count (напр. 100 → 1) слоты за
    # max_count+63 оставались на диске навсегда.
    for slot in range(max_count + 1, _MAX_BACKUPS + 1):
        extra = backup_path_for(project_path, slot)
        if os.path.isfile(extra):
            try:
                os.remove(extra)
            except OSError:
                pass
    _atomic_copy(project_path, backup_path_for(project_path, 1))
    return list_backups(project_path, max_count)


def list_backups(project_path: str, max_count: int = DEFAULT_BACKUP_COUNT) -> List[Dict]:
    """Существующие бэкапы, свежие первыми: [{path, slot, mtime, size}, ...]."""
    items = []
    for slot in range(1, max_count + 1):
        p = backup_path_for(project_path, slot)
        if os.path.isfile(p):
            try:
                st = os.stat(p)
                items.append({"path": p, "slot": slot, "mtime": st.st_mtime, "size": st.st_size})
            except OSError:
                continue
    return items


def restore_to_project(source_path: str, project_path: str) -> None:
    """Скопировать бэкап/автосохранение обратно в файл проекта (атомарно).

    Бросает исключение при ошибке — решение о сообщении пользователю принимает
    вызывающий (MainWindow._restore_from_source).
    """
    if not os.path.isfile(source_path):
        raise FileNotFoundError(f"Backup source not found: {source_path}")
    _atomic_copy(source_path, project_path)
