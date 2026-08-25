# -*- coding: utf-8 -*-
"""v0.8.2: Запуск SSH-сессии в альтернативном (системном) терминале ОС.

Приложение лишь порождает процесс (subprocess.Popen) с ssh-клиентом ОС
(`ssh.exe` входит в Windows 10/11 и почти во все Linux) — после запуска
связь с окном не нужна.

БЕЗОПАСНОСТЬ: пароль НЕ передаётся через аргументы командной строки
(он виден в `ps`/диспетчере задач). Внешний терминал = ssh ОС: пароль
пользователь вводит сам либо используется key auth (`ssh -i key -p port user@host`).

Настройки — простой JSON в ~/.sshmap_settings.json:
    {"external_terminal": "auto" | "windows_terminal" | "cmd" | "conhost"
                            | "x-terminal-emulator" | "gnome-terminal" | "konsole"
                            | "xfce4-terminal" | "alacritty" | "kitty"}
Отсутствие файла/ключа = "auto".
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

# ── Настройки (~/.sshmap_settings.json) ─────────────────────────────

SETTINGS_FILENAME = ".sshmap_settings.json"

# Ключи настроек внешнего терминала (значения settings key ↔ id терминала)
TERMINAL_CHOICES_WINDOWS = ["auto", "windows_terminal", "cmd", "conhost"]
TERMINAL_CHOICES_LINUX = [
    "auto", "x-terminal-emulator", "gnome-terminal", "konsole",
    "xfce4-terminal", "alacritty", "kitty",
]


def _settings_path() -> str:
    return os.path.join(os.path.expanduser("~"), SETTINGS_FILENAME)


def load_external_terminal_setting() -> str:
    """Прочитать настройку терминала из ~/.sshmap_settings.json ('auto' по умолчанию)."""
    try:
        import json
        with open(_settings_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        value = str(data.get("external_terminal", "auto")).strip().lower()
        valid = set(TERMINAL_CHOICES_WINDOWS if sys.platform == "win32"
                    else TERMINAL_CHOICES_LINUX)
        return value if value in valid else "auto"
    except Exception:
        return "auto"


def save_external_terminal_setting(value: str) -> bool:
    """Сохранить настройку (merge с остальными ключами файла). False при ошибке."""
    try:
        import json
        path = _settings_path()
        data = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
        data["external_terminal"] = value
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
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

    Windows: wt.exe → cmd.exe (всегда есть) → conhost.
    Linux: x-terminal-emulator / gnome-terminal / konsole / xfce4-terminal /
           alacritty / kitty.
    Возвращает id ("windows_terminal"/"cmd"/... ) или None, если ничего нет.
    """
    forced = load_external_terminal_setting()
    if sys.platform == "win32":
        order = {
            "windows_terminal": lambda: _which("wt.exe"),
            "cmd": lambda: _which("cmd.exe"),
            "conhost": lambda: _which("conhost.exe"),
            # auto: wt есть почти на всех Win10/11; cmd — гарантированный fallback
            "auto": lambda: _which("wt.exe") or _which("cmd.exe"),
        }
        finder = order.get(forced, order["auto"])
        result = finder()
        if result:
            return forced if forced in order and forced != "auto" else (
                "windows_terminal" if _which("wt.exe") else "cmd")
        # Явно выбранный терминал не найден через which → общий fallback.
        # AUDIT v0.8.3 (#3): conhost тоже участвует в fallback.
        for tid in ("windows_terminal", "cmd", "conhost"):
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
    - cmd/conhost:      `cmd /c start "" ssh ...` (пустой заголовок окна —
                        обязательный positional-аргумент start)
    - Linux gnome-terminal и родственные: `<term> -- bash -c "ssh ...; exec bash"`
      (окно не закрывается при разрыве сессии).
    Пароль никогда не входит в команду (см. докстринг модуля).
    """
    ssh_args = build_ssh_args(host, user, port, key_path, jump)

    if terminal == "windows_terminal":
        return ["wt.exe"] + ssh_args
    if terminal == "cmd":
        # `start "" prog args`: пустой заголовок обязателен, иначе первый
        # аргумент съедается как заголовок окна. Путь к ssh берём полный —
        # `start` ищет в текущем каталоге первым.
        ssh_exe = _which("ssh") or "ssh"
        return ["cmd.exe", "/c", "start", "", ssh_exe] + ssh_args[1:]
    if terminal == "conhost":
        # v0.9.3 fix: голый `conhost.exe ssh ...` не работает — conhost требует
        # команду через /c (иначе окно мигает и умирает). Запускаем как
        # `conhost cmd /c ssh ...`; ветка остаётся последним fallback'ом.
        ssh_exe = _which("ssh") or "ssh"
        return ["conhost.exe", "cmd.exe", "/c", ssh_exe] + ssh_args[1:]
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
