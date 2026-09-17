# -*- coding: utf-8 -*-
"""v0.9: Automatic collection of Linux server info over SSH (CPU/RAM/DISK/OS).

One batch of commands through a single exec_command() of the existing paramiko
stack — the output is marked with section markers (--MARKER--) and parsed
section by section.

NOT tied to the StatusChecker: that one does lightweight TCP probes without
authentication; credential data must not be passed to it (roadmap v0.9, task 5).

Usage:
    collector = SystemInfoCollector(server_data, password="...")
    collector.info_ready.connect(on_ready)    # (server_id, info_dict)
    collector.info_failed.connect(on_fail)    # (server_id, error_text)
    collector.start()

info_dict contains only the successfully parsed keys:
    os_name, cpu_model, cpu_cores, ram_gb, disk_gb
"""

from typing import Dict

from PySide6.QtCore import QThread, Signal

try:
    from ..models.server import ServerData
except ImportError:
    from models.server import ServerData


# ── Collection batch: one exec_command, output marked with markers ──────────
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

_TIMEOUT_S = 10          # overall timeout for the channel (roadmap: 5 s per command; the batch is light)
_SECTION_OS = "---OS---"
_SECTION_CPU = "---CPU---"
_SECTION_RAM = "---RAM---"
_SECTION_DISK = "---DISK---"
_SECTION_END = "---END---"


def bytes_to_gb(nbytes: float) -> str:
    """Format bytes → a GB string in the model's style ("8 gb", "100.5 gb").

    Divide by 1024^3 (GiB — as shown by free -b), round to one decimal place,
    and strip the trailing ".0".
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
    """Strip ANSI sequences, control characters, and whitespace at the ends."""
    import re
    line = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line)  # CSI … m/A/…
    return re.sub(r"[\x00-\x1f\x7f]", "", line).strip()


def parse_os_release(text: str) -> str:
    """PRETTY_NAME from /etc/os-release (quotes accounted for) or the lsb_release line."""
    for line in text.splitlines():
        line = _clean_text(line)
        if line.startswith("PRETTY_NAME"):
            _, _, value = line.partition("=")
            value = value.strip().strip('"').strip("'").strip()
            if value:
                return value
    # fallback: the lsb_release -ds output (the only line without "=")
    for line in text.splitlines():
        line = _clean_text(line)
        if line and "=" not in line and not line.startswith("---"):
            return line.strip('"').strip("'")
    return ""


def parse_cpu(text: str):
    """(cores:int|None, model:str) from nproc + 'model name : ...'."""
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
    """RAM bytes from free -b (the first number) or MemTotal from /proc/meminfo (kB)."""
    for line in text.splitlines():
        token = line.strip()
        if not token or not token[0].isdigit():
            continue
        first = token.split()[0]
        if first.isdigit():
            # meminfo gives kilobytes ("MemTotal:  16094 kB"), but the grep line
            # starts with 'M', so here we only get the number from free -b and the
            # pure kilobyte number from meminfo's second column; the kB case is
            # handled by the fallback below (MemTotal → *1024).
            return int(first)
    # fallback: "MemTotal:  16394256 kB"
    import re
    m = re.search(r"MemTotal:\s+(\d+)\s*kB", text)
    if m:
        return int(m.group(1)) * 1024
    return None


def parse_disk_bytes(text: str) -> int | None:
    """Root volume size from df -B1 --output=size / (the first numeric line)."""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("---"):  # the next section — no disk number will come
            break
        if s.isdigit():
            return int(s)
    return None


def parse_info_output(output: str) -> Dict[str, str]:
    """Parse the whole batch output by markers → a dict of finished values.

    Only non-empty values go into the dict; the field format matches the model
    (cpu_cores — as a string, ram/disk — "N gb").
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
    """One-shot thread: an SSH connection + one command batch + parsing.

    The signals are delivered to the GUI thread; receivers must re-check that
    the node still exists on the map.
    """

    info_ready = Signal(str, dict)   # server_id, info_dict
    info_failed = Signal(str, str)   # server_id, error_text

    def __init__(self, data: ServerData, password: str = "",
                 parent=None):
        super().__init__(parent)
        self.data = data
        self.password = password or ""

    # v0.9.3 fix: the collector is one-shot (no cancel flag inside run), so
    # "stopping" is just a bounded wait for its natural completion
    # (_TIMEOUT_S on the channel + parsing; see _shutdown_background_threads in MainWindow).
    def stop(self):
        self.wait(int((_TIMEOUT_S + 2) * 1000))

    def run(self):  # noqa: C901 — a flat chain of steps with early exits
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
                # a Windows server or a non-Linux shell: no markers — skip
                raise RuntimeError(
                    err.strip()[:200] or "no info batch markers in output "
                    "(non-Linux host?)")

            info = parse_info_output(output)
            if not info:
                raise RuntimeError("empty system info parsed")
            self.info_ready.emit(sid, info)
        except Exception as e:  # noqa: BLE001 — any error → a signal, not a crash
            self.info_failed.emit(sid, str(e))
