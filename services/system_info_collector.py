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
    + v1.6.6: disk_path, disk_free, disk_size, disk_note (the DATA mount)

v1.6.6 (ROADMAP task 4): the DISK section reads TWO mount points in ONE `df` — the ROOT (the
figure `disk` has always carried) and the node's **data mount** (`ServerData.disk_mount`, the
REQUEST; `""` means the DECLARED default `DISK_MOUNT_DEFAULT` = `/opt`). A server whose
capacity lives on a separate logical volume used to report the root's small number and hide
the filesystem that really holds the data; now both rows are read and `resolve_disk_answer()`
answers with the MOUNT POINT `df` really reported, so a host without a data mount answers `/`
instead of claiming one. A share is refused BY NAME: `NETWORK_FS_TYPES` is the DECLARED
classifier and a data mount on one of those filesystems is never reported as capacity — the
pair is left EMPTY and `disk_note` names what was found, which the window turns into a
sentence in the collection's own report (status bar + activity history). A path that does not
exist yields no row (and the shell's own `present`/`absent` token says so), never an error.
"""

from typing import Dict

from PySide6.QtCore import QThread, Signal

try:
    from ..models.server import ServerData
except ImportError:
    from models.server import ServerData

try:  # v1.6.6: the refusal of a data mount is a REPORT — it belongs in the activity ring
    from ..modules.logger import get_logger
except ImportError:  # pragma: no cover — the package layout (sshmap.services.*)
    from modules.logger import get_logger

log = get_logger(__name__)


# ── Collection batch: one exec_command, output marked with markers ──────────
# v1.6.6 (ROADMAP task 4): the DISK section reads the ROOT and the node's DATA MOUNT in ONE
# `df` (both paths as arguments, the 5 columns of `--output`), and the DISKMOUNT section
# carries the shell's own answer to "does that path exist at all" — a nonexistent path makes
# `df` print NOTHING for it, which is indistinguishable from "it lives on the root" without
# that token. `__DISK_MOUNT__` is the ONE placeholder, replaced by `build_info_batch()` with a
# single-quoted shell word (a path is user input and never reaches the remote shell unquoted).
DISK_MOUNT_TOKEN = "__DISK_MOUNT__"
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
df -B1 --output=source,fstype,size,avail,target / __DISK_MOUNT__ 2>/dev/null
echo ---DISKMOUNT---
[ -e __DISK_MOUNT__ ] && echo present || echo absent
echo ---END---
"""

_TIMEOUT_S = 10          # overall timeout for the channel (roadmap: 5 s per command; the batch is light)
_SECTION_OS = "---OS---"
_SECTION_CPU = "---CPU---"
_SECTION_RAM = "---RAM---"
_SECTION_DISK = "---DISK---"
_SECTION_DISKMOUNT = "---DISKMOUNT---"
_SECTION_END = "---END---"

#: The mount point measured when the node asks for none (v1.6.6). DECLARED here, named by the
#: dialog's placeholder and by `resolve_disk_mount()` — one home for one default.
DISK_MOUNT_DEFAULT = "/opt"

#: v1.6.6: the DECLARED classifier of a NETWORK filesystem. A mounted share is not local disk
#: — it is somebody else's capacity, and reporting it as this host's data mount would answer a
#: question nobody asked. The note a refusal leaves NAMES the entry it matched.
NETWORK_FS_TYPES = ("nfs", "nfs4", "cifs", "smbfs", "fuse.sshfs")

#: v1.6.6: the refusal KINDS the window turns into sentences (`disk_refusal_kind()`).
DISK_REFUSAL_NONE = ""
DISK_REFUSAL_MISSING = "missing"     # the requested path yielded no row / does not exist
DISK_REFUSAL_NETWORK = "network"     # the mount is a share — refused by name
DISK_NOTE_MISSING = "missing"        # the note the parser writes for a path that is not there


def sh_quote(text: str) -> str:
    """Quote a value as ONE POSIX-shell single-quoted word (PURE).

    The data mount is typed by the user and travels into a remote shell command, so it is
    never interpolated bare: the single quotes make every metacharacter literal, and a quote
    inside the value is closed, escaped and reopened (`'\\''`) — the standard, portable form.
    """
    return "'" + str("" if text is None else text).replace("'", "'\\''") + "'"


def resolve_disk_mount(value) -> str:
    """The REQUESTED data mount: the typed path, or the DECLARED default (PURE, v1.6.6).

    `""` (and a missing / whitespace-only value) selects `DISK_MOUNT_DEFAULT` — the request
    has ONE home (`ServerData.disk_mount`) and "unset" is not a second way to say `/opt`.
    """
    text = "" if value is None else str(value).strip()
    return text or DISK_MOUNT_DEFAULT


def build_info_batch(data_mount: str = "") -> str:
    """The collection batch with the requested mount quoted into it (PURE, v1.6.6).

    The token is replaced TWICE (the `df` argument and the existence test) with one and the
    same quoted word, so both halves of the read always describe the same path.
    """
    return INFO_BATCH.replace(DISK_MOUNT_TOKEN, sh_quote(resolve_disk_mount(data_mount)))


def is_network_fs(fstype: str) -> bool:
    """Is this `df` filesystem type a NETWORK one — a share, not local capacity? (PURE, v1.6.6)"""
    return str("" if fstype is None else fstype).strip().lower() in NETWORK_FS_TYPES



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
    """Root volume size from the legacy `df -B1 --output=size /` (the first numeric line).

    v1.6.6: the batch reads the two-row report instead (`parse_disk_report()`), and this
    number-only form stays as the DECLARED fallback for a `df` that does not accept
    `--output=source,fstype,size,avail,target` (BusyBox) — a host that cannot name its
    filesystems still gets its root figure.
    """
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("---"):  # the next section — no disk number will come
            break
        if s.isdigit():
            return int(s)
    return None


# ── v1.6.6: the DATA mount beside the root (`df -B1 --output=source,fstype,size,avail,target`) ──

def parse_disk_report(text: str) -> list:
    """The rows of ONE `df --output=source,fstype,size,avail,target` run (PURE, v1.6.6).

    Returns `[(source, fstype, size, avail, target), …]` with the two figures as ints. The
    header line (`Filesystem Type 1B-blocks Avail Mounted on`), a section marker and every
    unparsable line are DROPPED — so a path that does not exist simply yields NO row for it
    and never an error. The target is the rest of the line, so a mount point with a space
    survives; a `df` that refuses the `--output` list prints nothing and yields `[]`.
    """
    rows = []
    for line in text.splitlines():
        s = _clean_text(line)
        if not s or s.startswith("---"):
            continue
        parts = s.split(None, 4)
        if len(parts) < 5:
            continue
        source, fstype, size_raw, avail_raw, target = parts
        if not size_raw.isdigit() or not avail_raw.isdigit():
            continue  # the header and any other prose (`df` writes errors to stderr)
        rows.append((source, fstype, int(size_raw), int(avail_raw), target))
    return rows


def parse_disk_presence(text: str) -> bool:
    """Does the requested data path EXIST on that host? (PURE, v1.6.6)

    Reads the `present` / `absent` token of the DISKMOUNT section, which the shell decides
    (`[ -e <path> ]`). The token is needed because `df / <bad path>` prints the ROOT row for
    the first argument and nothing for the second — indistinguishable from "the data lives on
    the root" without it. A section that carries no token at all (an older batch, a hand-made
    fixture) answers True: the honest default is "the path is there", so a missing token can
    never turn a real measurement into a refusal.
    """
    for line in text.splitlines():
        token = _clean_text(line).lower()
        if token == "absent":
            return False
        if token == "present":
            return True
    return True


def _disk_gb_figure(nbytes) -> str:
    """The GB figure of a disk size, where a REAL ZERO stays a measurement (v1.6.6).

    `bytes_to_gb()` answers `""` for `0` because the collected `disk`/`ram` family uses the
    empty string for "nothing was measured". `df`'s own zero means something else — a
    filesystem that is completely full (`avail 0`) or empty (`size 0`) — and it must reach
    the card as `0 gb`, not vanish.
    """
    text = bytes_to_gb(nbytes)
    if text:
        return text
    try:
        return "0 gb" if float(nbytes) == 0.0 else ""
    except (TypeError, ValueError):
        return ""


def resolve_disk_answer(rows, present: bool = True) -> dict:
    """The ANSWER of the data-mount read, from the rows `df` really printed (PURE, v1.6.6).

    Returns `{"path", "free", "size", "note"}` where `path` is the MOUNT POINT `df` reported
    (never the typed request — a data directory that lives on the root answers `/`, which is
    the truth a collapsed request/answer pair would have hidden) and `free`/`size` are GB
    figures; `note` is `""` (nothing to say), `DISK_NOTE_MISSING` or the NAME of the network
    filesystem that was refused.

    The rule, in order:

    * the requested path does not exist (`present` False) → nothing is measured;
    * the rows carry no usable candidate at all → nothing is measured;
    * the answer is the ONE non-root row `df` printed when the requested path has a filesystem of its
      own, and the ROOT row (`/`) when it has none — that row is what was really measured;
    * that row's filesystem type is a NETWORK one → refused BY NAME, pair left EMPTY;
    * otherwise → the mount point and its two figures.
    """
    if not present:
        return {"path": "", "free": "", "size": "", "note": DISK_NOTE_MISSING}
    root = None
    extra = None
    for row in rows or ():
        try:
            _source, _fstype, _size, _avail, target = row
        except (TypeError, ValueError):
            continue
        if str(target).strip() == "/":
            if root is None:
                root = row
        else:
            extra = row  # `df` was given two paths, so there is at most one non-root row
    chosen = extra if extra is not None else root
    if chosen is None:
        return {"path": "", "free": "", "size": "", "note": DISK_NOTE_MISSING}
    _source, fstype, size, avail, target = chosen
    if is_network_fs(fstype):
        return {"path": "", "free": "", "size": "", "note": str(fstype).strip().lower()}
    return {"path": str(target).strip(),
            "free": _disk_gb_figure(avail),
            "size": _disk_gb_figure(size),
            "note": ""}


def disk_refusal_kind(note) -> str:
    """The KIND of a data-mount refusal, from the note the parser wrote (PURE, v1.6.6).

    `""` — nothing was refused; `DISK_REFUSAL_MISSING` — the requested path is not there;
    `DISK_REFUSAL_NETWORK` — the mount is a share, and the note itself NAMES the filesystem
    type that made it one (which is what "refused by name" means). The window composes the
    sentence from this kind; the collector logs it in English.
    """
    text = str("" if note is None else note).strip().lower()
    if not text:
        return DISK_REFUSAL_NONE
    if text == DISK_NOTE_MISSING:
        return DISK_REFUSAL_MISSING
    return DISK_REFUSAL_NETWORK if is_network_fs(text) else DISK_REFUSAL_NONE


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
        if s in (_SECTION_OS, _SECTION_CPU, _SECTION_RAM, _SECTION_DISK, _SECTION_DISKMOUNT):
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

    # v1.6.6 (ROADMAP task 4): the TWO-mount read. The ROOT keeps the figure it ships
    # (`disk_gb`, whose number the inventory's sort key parses) and the DATA-mount pair is
    # the answer to the question the release is about. The family is emitted as ONE unit —
    # path / free / size / note — so the ONE write path can tell "measured" (an answer or a
    # NAMED refusal) from "the collection said nothing about a data mount at all" (a legacy
    # batch, an old fixture): the first WRITES the pair, the second leaves it alone.
    disk_text = "\n".join(sections.get(_SECTION_DISK, []))
    rows = parse_disk_report(disk_text)
    if rows:
        root = next((row for row in rows if str(row[4]).strip() == "/"), None)
        if root is not None:
            root_gb = bytes_to_gb(root[2])
            if root_gb:
                result["disk_gb"] = root_gb
        answer = resolve_disk_answer(
            rows, parse_disk_presence("\n".join(sections.get(_SECTION_DISKMOUNT, []))))
        result["disk_path"] = answer["path"]
        result["disk_free"] = answer["free"]
        result["disk_size"] = answer["size"]
        result["disk_note"] = answer["note"]

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

                # v1.6.6 (ROADMAP task 4): the batch carries THIS node's requested data mount
                # (`build_info_batch` quotes it into the `df` argument and the existence test).
                stdin, stdout, stderr = client.exec_command(
                    build_info_batch(getattr(self.data, "disk_mount", "")),
                    timeout=_TIMEOUT_S)
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
            # v1.6.6 (ROADMAP task 4): a refused data mount is NOT silence — it travels as a
            # sentence in the collection's own report. The English line below reaches the log
            # file AND the activity ring (the v1.5.2 tap); the window composes the translated
            # status-bar sentence from the same note. A share is named by its filesystem type.
            self._log_disk_note(info)
            self.info_ready.emit(sid, info)
        except Exception as e:  # noqa: BLE001 — any error → a signal, not a crash
            self.info_failed.emit(sid, str(e))

    def _log_disk_note(self, info: dict) -> None:
        """Write the ONE English line of a refused data mount (v1.6.6; never raises).

        Log lines are never translated (the activity panel's own rule), so this is the one
        place the refusal is spelled out for the history; the card's status-bar sentence is the
        window's half of the same fact, composed from the same note.
        """
        try:
            note = str((info or {}).get("disk_note") or "")
            kind = disk_refusal_kind(note)
            if kind == DISK_REFUSAL_NETWORK:
                log.info("Data mount %s is a network filesystem (%s) on %s — "
                         "not reported as capacity",
                         resolve_disk_mount(getattr(self.data, "disk_mount", "")),
                         note, self.data.host)
            elif kind == DISK_REFUSAL_MISSING:
                log.info("Data mount %s was not found on %s — nothing was measured",
                         resolve_disk_mount(getattr(self.data, "disk_mount", "")),
                         self.data.host)
        except Exception:  # noqa: BLE001 — a report is a side channel
            pass

