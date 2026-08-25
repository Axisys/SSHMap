# -*- coding: utf-8 -*-
"""v0.9: Автосбор данных о Linux-сервере по SSH (CPU/RAM/DISK/OS).

Один батч команд через один exec_command() существующего paramiko-стека —
вывод размечен маркерами секций (--MARKER--) и парсится по секциям.

НЕ привязан к StatusChecker'у: тот делает лёгкие TCP-пробы без аутентификации,
авторизационные данные туда тащить нельзя (roadmap v0.9, задача 5).

Использование:
    collector = SystemInfoCollector(server_data, password="...")
    collector.info_ready.connect(on_ready)    # (server_id, info_dict)
    collector.info_failed.connect(on_fail)    # (server_id, error_text)
    collector.start()

info_dict содержит только успешно разобранные ключи:
    os_name, cpu_model, cpu_cores, ram_gb, disk_gb
"""

from typing import Dict

from PySide6.QtCore import QThread, Signal

try:
    from ..models.server import ServerData
except ImportError:
    from models.server import ServerData


# ── Батч сбора: один exec_command, вывод размечен маркерами ──────────
INFO_BATCH = r"""
echo ---OS---
uname -srmo 2>/dev/null
cat /etc/os-release 2>/dev/null || lsb_release -ds 2>/dev/null
echo ---CPU---
nproc 2>/dev/null
grep -m1 'model name' /proc/cpuinfo 2>/dev/null
echo ---RAM---
free -b 2>/dev/null | awk '/Mem:/{print $2}'
grep MemTotal /proc/meminfo 2>/dev/null
echo ---DISK---
df -B1 --output=size / 2>/dev/null | tail -1
echo ---END---
"""

_TIMEOUT_S = 10          # общий таймаут на канал (roadmap: 5 c на команду; батч лёгкий)
_SECTION_OS = "---OS---"
_SECTION_CPU = "---CPU---"
_SECTION_RAM = "---RAM---"
_SECTION_DISK = "---DISK---"
_SECTION_END = "---END---"


def bytes_to_gb(nbytes: float) -> str:
    """Формат байтов → строка GB в стиле модели («8 gb», «100.5 gb»).

    Делим на 1024^3 (GiB — как показывает free -b), округляем до одного знака,
    хвостовой «.0» убираем.
    """
    try:
        gb = float(nbytes) / (1024.0 ** 3)
    except (TypeError, ValueError):
        return ""
    gb = round(gb, 1)
    if gb <= 0:
        return ""
    text = f"{gb:g}"
    return f"{text} gb"


def _clean_text(line: str) -> str:
    """Убрать ANSI-последовательности, управляющие символы и пробелы по краям."""
    import re
    line = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line)  # CSI … m/A/…
    return re.sub(r"[\x00-\x1f\x7f]", "", line).strip()


def parse_os_release(text: str) -> str:
    """PRETTY_NAME из /etc/os-release (с учётом кавычек) или строка lsb_release."""
    for line in text.splitlines():
        line = _clean_text(line)
        if line.startswith("PRETTY_NAME"):
            _, _, value = line.partition("=")
            value = value.strip().strip('"').strip("'").strip()
            if value:
                return value
    # fallback: вывод lsb_release -ds (единственная строка без "=")
    for line in text.splitlines():
        line = _clean_text(line)
        if line and "=" not in line and not line.startswith("---"):
            return line.strip('"').strip("'")
    return ""


def parse_cpu(text: str):
    """(cores:int|None, model:str) из nproc + 'model name : ...'."""
    cores = None
    model = ""
    for line in text.splitlines():
        line = line.strip()
        if line.isdigit() and cores is None:
            cores = int(line)
        elif ":" in line and "model name" in line:
            model = line.split(":", 1)[1].strip()
    return cores, model


def parse_ram_bytes(text: str):
    """Байты RAM из free -b (первая цифра) или MemTotal из /proc/meminfo (кБ)."""
    for line in text.splitlines():
        token = line.strip()
        if not token or not token[0].isdigit():
            continue
        first = token.split()[0]
        if first.isdigit():
            # meminfo даёт килобайты («MemTotal:  16094 kB»), но grep-строка
            # начинается с 'M', сюда попадает только число из free -b и чистое
            # число-килобайт из второй колонки meminfo; кБ-случай обрабатывает
            # fallback ниже (MemTotal → *1024).
            return int(first)
    # fallback: "MemTotal:  16394256 kB"
    import re
    m = re.search(r"MemTotal:\s+(\d+)\s*kB", text)
    if m:
        return int(m.group(1)) * 1024
    return None


def parse_disk_bytes(text: str) -> int | None:
    """Размер корневого тома из df -B1 --output=size / (первая числовая строка)."""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("---"):  # следующая секция — числа диска не будет
            break
        if s.isdigit():
            return int(s)
    return None


def parse_info_output(output: str) -> Dict[str, str]:
    """Разобрать весь батч-вывод по маркерам → словарь готовых значений.

    В словарь попадают только непустые значения; формат полей совпадает
    с моделью (cpu_cores — строкой, ram/disk — «N gb»).
    """
    sections = {}
    current = None
    for line in output.splitlines():
        line = line.rstrip("\r")
        s = line.strip()
        if s in (_SECTION_OS, _SECTION_CPU, _SECTION_RAM, _SECTION_DISK):
            current = s
            sections[current] = []
        elif s == _SECTION_END:
            break
        elif current is not None:
            sections[current].append(line)

    result: Dict[str, str] = {}

    os_name = parse_os_release("\n".join(sections.get(_SECTION_OS, [])))
    if os_name:
        result["os_name"] = os_name

    cores, model = parse_cpu("\n".join(sections.get(_SECTION_CPU, [])))
    if cores:
        result["cpu_cores"] = str(cores)
    if model:
        result["cpu_model"] = model

    ram = parse_ram_bytes("\n".join(sections.get(_SECTION_RAM, [])))
    ram_gb = bytes_to_gb(ram) if ram else ""
    if ram_gb:
        result["ram_gb"] = ram_gb

    disk = parse_disk_bytes("\n".join(sections.get(_SECTION_DISK, [])))
    disk_gb = bytes_to_gb(disk) if disk else ""
    if disk_gb:
        result["disk_gb"] = disk_gb

    return result


class SystemInfoCollector(QThread):
    """Одноразовый поток: SSH-подключение + один батч команд + парсинг.

    Сигналы доставляются в GUI-поток; приёмники обязаны перепроверить,
    что узел ещё существует на карте.
    """

    info_ready = Signal(str, dict)   # server_id, info_dict
    info_failed = Signal(str, str)   # server_id, error_text

    def __init__(self, data: ServerData, password: str = "",
                 parent=None):
        super().__init__(parent)
        self.data = data
        self.password = password or ""

    # v0.9.3 fix: коллектор одноразовый (без cancel-флага внутри run), поэтому
    # «остановка» — это просто ограниченное ожидание естественного завершения
    # (_TIMEOUT_S на канал + парсинг; см. _shutdown_background_threads в MainWindow).
    def stop(self):
        self.wait(int((_TIMEOUT_S + 2) * 1000))

    def run(self):  # noqa: C901 — плоская цепочка шагов с ранними выходами
        sid = self.data.id
        try:
            import paramiko
            from services.credential_manager import get_credential_manager
            try:
                from modules.host_key_policy import SshKnownHostsPolicy
            except ImportError:
                from modules.host_key_policy import SshKnownHostsPolicy

            final_password = self.password
            if not final_password:
                try:
                    cm = get_credential_manager()
                    final_password = cm.load_password(sid) or ""
                except Exception:
                    final_password = ""

            client = paramiko.SSHClient()
            policy = SshKnownHostsPolicy(
                hostname=self.data.host, port=self.data.ssh_port or 22)
            policy.apply_to_client(client)
            try:
                connect_kwargs = dict(
                    hostname=self.data.host,
                    username=self.data.user,
                    port=self.data.ssh_port or 22,
                    timeout=_TIMEOUT_S,
                    banner_timeout=_TIMEOUT_S,
                )
                if self.data.key_path:
                    connect_kwargs.update(key_filename=self.data.key_path,
                                          look_for_keys=False, allow_agent=True)
                    if final_password:
                        connect_kwargs["password"] = final_password
                elif final_password:
                    connect_kwargs.update(password=final_password,
                                          look_for_keys=False, allow_agent=False)
                else:
                    connect_kwargs.update(look_for_keys=True, allow_agent=True)
                client.connect(**connect_kwargs)

                stdin, stdout, stderr = client.exec_command(INFO_BATCH, timeout=_TIMEOUT_S)
                stdin.close()
                output = stdout.read().decode("utf-8", errors="replace")
                err = stderr.read().decode("utf-8", errors="replace")
            finally:
                client.close()

            if _SECTION_END not in output:
                # Windows-сервер или не-Linux shell: маркеров нет — пропускать
                raise RuntimeError(
                    err.strip()[:200] or "no info batch markers in output "
                    "(non-Linux host?)")

            info = parse_info_output(output)
            if not info:
                raise RuntimeError("empty system info parsed")
            self.info_ready.emit(sid, info)
        except Exception as e:  # noqa: BLE001 — любая ошибка → сигнал, не падение
            self.info_failed.emit(sid, str(e))
