# -*- coding: utf-8 -*-
"""v0.8.2: Запуск SSH-сессии в альтернативном (системном) терминале ОС.

Приложение лишь порождает процесс (subprocess.Popen) с ssh-клиентом ОС
(`ssh.exe` входит в Windows 10/11 и почти во все Linux) — после запуска
связь с окном не нужна.

БЕЗОПАСНОСТЬ: пароль НЕ передаётся через аргументы командной строки
(он виден в `ps`/диспетчере задач). Внешний терминал = ssh ОС: пароль
пользователь вводит сам либо используется key auth (`ssh -i key -p port user@host`).

Настройки — единый ~/.sshmap/config.json (i18n.load_config/save_config, атомарная
запись), ключ:
    "external_terminal": "auto" | "windows_terminal" | "cmd"
                         | "x-terminal-emulator" | "gnome-terminal" | "konsole"
                         | "xfce4-terminal" | "alacritty" | "kitty"
Отсутствие ключа = "auto".

v1.1.2RC1 (N2): пресет «conhost» УБРАН — conhost.exe не лаунчер (не принимает /c,
позиционные аргументы трактует как handle консоли/процесс-сервер), собранная команда
гарантированно не работала. Старое значение конфига "conhost" трактуется как "cmd"
(окно cmd.exe — это и есть классический conhost): маппинг в
load_external_terminal_setting() + нормализация при миграции legacy-файла;
build_command("conhost", ...) остаётся алиасом "cmd" для прямых вызовов.

v1.1 (ROADMAP задача 7): до v1.0 настройка жила в отдельном ~/.sshmap_settings.json —
у приложения было два источника настроек. Теперь при чтении выполняется миграция:
если ключа нет в config.json, но есть в старом файле — значение копируется в
config.json (save_config), старый файл удаляется (best effort). Запись идёт ТОЛЬКО
в config.json. UI выбора пресета — секция SSHConnectDialog (v0.9.9.2) и вкладка
«Общие» диалога настроек (v1.1).
"""

import os
import shutil
import subprocess
import sys
from typing import Optional, List

try:
    from .logger import get_logger
except ImportError:
    from modules.logger import get_logger

log = get_logger(__name__)

# ── Настройки (единый ~/.sshmap/config.json; v1.1 — ROADMAP задача 7) ─────────

# Имя СТАРОГО файла настроек (v0.8.2–v1.0): нужен только для миграции при чтении.
SETTINGS_FILENAME = ".sshmap_settings.json"
LEGACY_SETTINGS_FILENAME = SETTINGS_FILENAME  # псевдоним — яснее по смыслу

# Ключи настроек внешнего терминала (значения settings key ↔ id терминала).
# v1.1.2RC1 (N2): «conhost» убран из списка — conhost.exe не лаунчер (см. докстринг
# модуля); старое сохранённое значение "conhost" маппится на "cmd" в
# load_external_terminal_setting() (backward-compat).
TERMINAL_CHOICES_WINDOWS = ["auto", "windows_terminal", "cmd"]
TERMINAL_CHOICES_LINUX = [
    "auto", "x-terminal-emulator", "gnome-terminal", "konsole",
    "xfce4-terminal", "alacritty", "kitty",
]


def _settings_path() -> str:
    """v1.1: путь ЕДИНОГО файла настроек — ~/.sshmap/config.json (был .sshmap_settings.json)."""
    return os.path.join(os.path.expanduser("~"), ".sshmap", "config.json")


def _legacy_settings_path() -> str:
    """Путь СТАРОГО отдельного файла (v0.8.2–v1.0) — только для миграции."""
    return os.path.join(os.path.expanduser("~"), LEGACY_SETTINGS_FILENAME)


def _read_legacy_settings() -> Optional[dict]:
    """Содержимое старого ~/.sshmap_settings.json (None — отсутствует/бит)."""
    try:
        import json
        with open(_legacy_settings_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _migrate_legacy_settings() -> Optional[str]:
    """v1.1 (ROADMAP задача 7): разовая миграция ключа из старого файла в config.json.

    Вызывается при чтении, когда ключа ещё нет в config.json: значение копируется
    в config.json (save_config — атомарная merge-запись), затем старый файл
    удаляется (best effort; если запись не удалась — файл остаётся и миграция
    повторится при следующем чтении). Возвращает смигрированное значение или None.
    """
    legacy = _read_legacy_settings()
    if not legacy or "external_terminal" not in legacy:
        return None
    raw = str(legacy["external_terminal"]).strip().lower()
    # v1.1.2RC1 (N2): «conhost» больше не пресет — нормализуем в "cmd" ДО записи,
    # чтобы мёртвое значение не закреплялось в config.json.
    if raw == "conhost":
        raw = "cmd"
    try:
        from i18n import save_config as _save_cfg
        if not _save_cfg({"external_terminal": raw}):
            return raw  # запись не удалась — значение отдаём, файл оставляем
    except Exception:
        return raw
    try:
        os.remove(_legacy_settings_path())
    except OSError:
        pass  # удалить не удалось (read-only home и т.п.) — ключ уже в config.json
    log.info("Migrated external_terminal setting from %s to config.json",
             LEGACY_SETTINGS_FILENAME)
    return raw


def load_external_terminal_setting() -> str:
    """Прочитать настройку терминала из ~/.sshmap/config.json ('auto' по умолчанию).

    v1.1 (ROADMAP задача 7): единый файл настроек. Если ключа нет в config.json,
    но есть в старом ~/.sshmap_settings.json — миграция при чтении
    (_migrate_legacy_settings()). Невалидное значение → 'auto'.

    v1.1.2RC1 (N2): backward-compat — старое сохранённое значение "conhost"
    трактуется как "cmd" (конфиг на диске НЕ перезаписывается, маппинг при чтении).
    """
    value = None
    try:
        from i18n import load_config as _load_cfg
        cfg = _load_cfg() or {}
        if "external_terminal" in cfg:
            value = str(cfg.get("external_terminal", "auto")).strip().lower()
        else:
            value = _migrate_legacy_settings()
    except Exception:
        return "auto"
    if value is None:
        value = "auto"
    # v1.1.2RC1 (N2): «conhost» убран из пресетов — старые конфиги читаются как "cmd".
    if value == "conhost":
        value = "cmd"
    valid = set(TERMINAL_CHOICES_WINDOWS if sys.platform == "win32"
                else TERMINAL_CHOICES_LINUX)
    return value if value in valid else "auto"


def save_external_terminal_setting(value: str) -> bool:
    """Сохранить настройку в ~/.sshmap/config.json (атомарная merge-запись).

    v1.1 (ROADMAP задача 7): старый ~/.sshmap_settings.json больше НЕ пишется;
    если он ещё существует с ключом — load_external_terminal_setting() смигрирует
    его и удалит файл. False при ошибке записи.
    """
    try:
        from i18n import save_config as _save_cfg
        return bool(_save_cfg({"external_terminal": value}))
    except Exception as e:
        log.warning("Cannot save external terminal setting: %s", e)
        return False


# ── detect_terminal ────────────────────────────────────────────────

def _which(name: str) -> Optional[str]:
    try:
        return shutil.which(name)
    except Exception:
        return None


def detect_terminal() -> Optional[str]:
    """Найти доступный эмулятор терминала на текущей ОС.

    Windows: wt.exe → cmd.exe (всегда есть).
    Linux: x-terminal-emulator / gnome-terminal / konsole / xfce4-terminal /
           alacritty / kitty.
    Возвращает id ("windows_terminal"/"cmd"/... ) или None, если ничего нет.

    v1.1.2RC1 (N2): «conhost» из fallback-цепочки убран — conhost.exe не лаунчер
    (см. докстринг модуля); окно cmd.exe и есть классический conhost, а cmd.exe
    на Windows всегда есть, так что цепочка wt → cmd покрывает все случаи.
    """
    forced = load_external_terminal_setting()
    if sys.platform == "win32":
        order = {
            "windows_terminal": lambda: _which("wt.exe"),
            "cmd": lambda: _which("cmd.exe"),
            # auto: wt есть почти на всех Win10/11; cmd — гарантированный fallback
            "auto": lambda: _which("wt.exe") or _which("cmd.exe"),
        }
        finder = order.get(forced, order["auto"])
        result = finder()
        if result:
            return forced if forced in order and forced != "auto" else (
                "windows_terminal" if _which("wt.exe") else "cmd")
        # Явно выбранный терминал не найден через which → общий fallback.
        for tid in ("windows_terminal", "cmd"):
            if order[tid]():
                return tid
        return None

    # Linux / macOS
    candidates = [c for c in TERMINAL_CHOICES_LINUX if c != "auto"]
    if forced != "auto" and forced in candidates:
        if _which(forced):
            return forced
    for name in candidates:
        if _which(name):
            return name
    # macOS fallback: Terminal.app через open
    if sys.platform == "darwin":
        return "open_terminal"
    return None


def ssh_client_available() -> bool:
    return _which("ssh") is not None


# ── build_command ──────────────────────────────────────────────────

def build_ssh_args(host: str, user: str, port: int = 22,
                   key_path: Optional[str] = None,
                   jump: Optional[str] = None) -> List[str]:
    """Аргументы ssh-клиента ОС (без самого 'ssh').

    known_hosts — системный (~/.ssh/known_hosts), НЕ ~/.sshmap.
    """
    args = ["ssh"]
    if port and int(port) != 22:
        args += ["-p", str(int(port))]
    if key_path:
        args += ["-i", key_path]
    if jump:
        args += ["-J", jump]
    args += ["-o", "ConnectTimeout=10"]
    args.append(f"{user}@{host}" if user else host)
    return args


def _sh_quote(s: str) -> str:
    """Экранирование одного аргумента для bash -c '...' (POSIX single-quote).

    v0.9.4-fix: пути к ключу с пробелами/кавычками ломали shell-команду,
    собранную конкатенацией. Используется ТОЛЬКО для Linux/macOS-веток,
    где команда передаётся строкой в `bash -c`.
    """
    return "'" + s.replace("'", "'\"'\"'") + "'"


def _shell_join(args: List[str]) -> str:
    """Склеить argv в безопасную sh-строку."""
    return " ".join(_sh_quote(a) for a in args)


def build_command(terminal: str, host: str, user: str, port: int = 22,
                  key_path: Optional[str] = None,
                  jump: Optional[str] = None) -> List[str]:
    """Полная команда запуска внешнего терминала с ssh внутри.

    - Windows Terminal: `wt.exe ssh ...`
    - cmd:              `cmd /c start "" ssh ...` (пустой заголовок окна —
                        обязательный positional-аргумент start)
    - Linux gnome-terminal и родственные: `<term> -- bash -c "ssh ...; exec bash"`
      (окно не закрывается при разрыве сессии).
    Пароль никогда не входит в команду (см. докстринг модуля).

    v1.1.2RC1 (N2): ветка «conhost» удалена — команда `["conhost.exe", "cmd.exe",
    "/c", ssh_exe]` была нерабочей (conhost не лаунчер, /c не принимает; прежний
    докстринг «cmd/conhost: cmd /c start» расходился с реальной веткой). Старый id
    "conhost" маппится на "cmd" — окно cmd.exe и есть классический conhost.
    """
    # v1.1.2RC1 (N2): backward-compat для прямых вызовов со старым id.
    if terminal == "conhost":
        terminal = "cmd"

    ssh_args = build_ssh_args(host, user, port, key_path, jump)

    if terminal == "windows_terminal":
        return ["wt.exe"] + ssh_args
    if terminal == "cmd":
        # `start "" prog args`: пустой заголовок обязателен, иначе первый
        # аргумент съедается как заголовок окна. Путь к ssh берём полный —
        # `start` ищет в текущем каталоге первым.
        ssh_exe = _which("ssh") or "ssh"
        return ["cmd.exe", "/c", "start", "", ssh_exe] + ssh_args[1:]
    if terminal == "open_terminal":  # macOS
        # v0.9.4-fix: `open -a Terminal bash -c ...` не работает — open так
        # аргументы не передаёт. Корректный способ — osascript: открываем
        # Terminal.app и выполняем в нём команду (окно переживает разрыв
        # сессии за счёт `exec bash`).
        script = f"{_shell_join(ssh_args)}; exec bash"
        return ["osascript", "-e",
                'tell application "Terminal" to do script ' + _sh_quote(script)]
    # Linux-семейство: gnome-terminal/konsole/xfce4-terminal/alacritty/kitty/
    # x-terminal-emulator
    shell_cmd = f"{_shell_join(ssh_args)}; exec bash"
    if terminal in ("gnome-terminal", "konsole", "xfce4-terminal",
                    "x-terminal-emulator", "alacritty", "kitty"):
        exe = _which(terminal) or terminal
        if terminal == "konsole":
            return [exe, "-e", "bash", "-c", shell_cmd]
        if terminal == "kitty":
            return [exe, "bash", "-c", shell_cmd]
        if terminal == "alacritty":
            return [exe, "-e", "bash", "-c", shell_cmd]
        # gnome-terminal / xfce4-terminal / x-terminal-emulator
        return [exe, "--", "bash", "-c", shell_cmd]
    raise ValueError(f"Unknown terminal id: {terminal!r}")


# ── launch ─────────────────────────────────────────────────────────

def launch(command: Optional[List[str]] = None, host: str = "", user: str = "",
           port: int = 22, key_path: Optional[str] = None,
           jump: Optional[str] = None) -> bool:
    """Породить процесс внешнего терминала (subprocess.Popen).

    Два режима (AUDIT v0.8.3 #4 — явная сигнатура вместо kwargs.pop):
      - command задан  → запустить его как есть;
      - command=None   → detect_terminal() + build_command(host, user, ...);
        вызов без host теперь даёт внятную ошибку, а не KeyError.
    Windows: CREATE_NEW_CONSOLE — окно живёт своей жизнью
    (AUDIT v0.8.3 #2: DETACHED_PROCESS из старого кода убран — флаги
    взаимно исключающие, работала только вторая перезапись).
    Возвращает True/False; исключение Popen логируется и превращается в False.
    """
    if command is None:
        if not host:
            log.error("launch() without command requires host")
            return False
        term = detect_terminal()
        if not term:
            return False
        command = build_command(term, host, user, port, key_path, jump)
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    try:
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
        )
        log.info("External terminal launched: %s", command[0])
        return True
    except FileNotFoundError as e:
        log.error("External terminal binary not found (%s): %s", command[0], e)
        return False
    except OSError as e:
        log.error("Popen failed for external terminal: %s", e)
        return False


def connect_external(host: str, user: str, port: int = 22,
                     key_path: Optional[str] = None,
                     jump: Optional[str] = None) -> tuple:
    """Полный путь: detect → build → launch.

    Возвращает (ok: bool, error_code: str|None):
      error_code ∈ {None, 'no_ssh_client', 'no_terminal', 'popen_failed'}.
    """
    if not ssh_client_available():
        return False, "no_ssh_client"
    term = detect_terminal()
    if not term:
        return False, "no_terminal"
    ok = launch(build_command(term, host, user, port, key_path, jump))
    return (True, None) if ok else (False, "popen_failed")
