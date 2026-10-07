# -*- coding: utf-8 -*-
"""Automatic collection of Linux server info over SSH — CPU / RAM / DISK / OS (§24, §46).
ONE batch of commands through a single `exec_command()` of the existing paramiko stack, marked with
section markers and parsed section by section — deliberately NOT tied to the `StatusChecker` (that one
makes lightweight TCP probes WITHOUT authentication, so credentials must never reach it).
`SystemInfoCollector(data, password=…)` emits `info_ready(server_id, info_dict)` /
`info_failed(server_id, error_text)`; `info_dict` carries `os_name`, `cpu_model`, `cpu_cores`,
`ram_gb`, `disk_gb` and the DEVICE list `disk_devices` beside the DATA-mount family `disk_path` /
`disk_free` / `disk_size` / `disk_note`.

Two REQUEST/ANSWER pairs beside the root: the data MOUNT (`disk_mount`, `""` ⇒ `DISK_MOUNT_DEFAULT`) is
answered by the mount point `df` reported (a share refused BY NAME), the DEVICE choice (`disk_device`)
by that device's `lsblk -d` capacity — a name the listing does not hold is REPORTED, never a guess."""

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
# The DISK section reads the ROOT and the node's DATA MOUNT in ONE `df` (both paths as arguments, the
# 5 columns of `--output`), the DISKS section lists the physical devices (`lsblk -d`, no user input)
# and the DISKMOUNT section answers "does that path exist". `__DISK_MOUNT__` is ONE single-quoted word
# (user input never reaches the shell bare) and the section's SECOND command is the POSIX ROOT fallback.
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
df -k / 2>/dev/null | awk 'END{if (NF>=5) printf "%.0f\n", $(NF-4)*1024}'
echo ---DISKS---
lsblk -d -n -b -o NAME,SIZE,TYPE 2>/dev/null
echo ---DISKMOUNT---
[ -e __DISK_MOUNT__ ] && echo present || echo absent
echo ---INODES---
df -i -P / __DISK_MOUNT__ 2>/dev/null
echo ---END---
"""

_TIMEOUT_S = 10          # overall timeout for the channel (roadmap: 5 s per command; the batch is light)
_SECTION_OS = "---OS---"
_SECTION_CPU = "---CPU---"
_SECTION_RAM = "---RAM---"
_SECTION_DISK = "---DISK---"
_SECTION_DISKS = "---DISKS---"
_SECTION_DISKMOUNT = "---DISKMOUNT---"
_SECTION_INODES = "---INODES---"
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
DISK_REFUSAL_DEVICE = "device"       # the named DEVICE is not in the `lsblk` listing
DISK_NOTE_MISSING = "missing"        # the note the parser writes for a path that is not there
DISK_NOTE_DEVICE_MISSING = "device-missing"   # the note the collector writes for a vanished device

#: The `lsblk` TYPE that declares a PHYSICAL disk: `sda`, `nvme0n1`, `vda`, `xvda`, `mmcblk0` carry
#: it, while `loop`, `rom`, `dm-*` and `md*` carry their own — so the filter is a declaration about
#: the DEVICE, never about the shape of its name.
DISK_TYPE_PHYSICAL = "disk"

#: v1.8.4: the inode use at which the card stops saying only "N gb free" — a filesystem can sit at
#: 40 % free SPACE and 100 % used INODES, so the percentage is a fact the card carries and this is
#: the DECLARED line above which the mount's own info line names it (below it the figure lives in
#: the tooltip, so an ordinary card's line stays byte for byte what it was).
INODE_ALERT_PERCENT = 90


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
    """The ROOT size in bytes from a bare-number line of the DISK section (PURE).

    The section carries TWO readers: `parse_disk_report()` reads the 5-column table of
    `df --output=…` (the mounted pair), and this one reads the size-only line the batch's
    `df -k / | awk` fallback writes — the GNU-only `--output` list is refused by a BusyBox
    `df`, which prints NOTHING for it, so the fallback is what answers the root figure there.
    The first numeric line wins; a section marker ends the scan.
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
    """The KIND of a refusal, from the note the parser wrote (PURE, v1.6.6).

    `""` — nothing was refused; `DISK_REFUSAL_MISSING` — the requested path is not there;
    `DISK_REFUSAL_DEVICE` — the DEVICE the card is about is not in the `lsblk` listing;
    `DISK_REFUSAL_NETWORK` — the mount is a share, and the note itself NAMES the filesystem
    type that made it one (which is what "refused by name" means). The window composes the
    sentence from this kind; the collector logs it in English.
    """
    text = str("" if note is None else note).strip().lower()
    if not text:
        return DISK_REFUSAL_NONE
    if text == DISK_NOTE_MISSING:
        return DISK_REFUSAL_MISSING
    if text == DISK_NOTE_DEVICE_MISSING:
        return DISK_REFUSAL_DEVICE
    return DISK_REFUSAL_NETWORK if is_network_fs(text) else DISK_REFUSAL_NONE


def disk_refusal_text(t, note, alias: str, mount: str = "", device: str = "") -> str:
    """The ONE sentence of a refused disk request (PURE over `t`; `""` — the note is no refusal).

    The three shipped `status.disk_*` keys carry it, and BOTH surfaces read them HERE: the status
    bar of the collection that met the refusal, and the card's own tooltip, which keeps saying it
    for as long as the note is stored beside the answers it explains (v1.8rc6, N35). The composer
    itself stays i18n-agnostic — the translator is an ARGUMENT (the `ui/unmanaged.py` shape), so a
    caller without one renders the key and never a hardcoded English sentence.
    """
    kind = disk_refusal_kind(note)
    if kind == DISK_REFUSAL_NETWORK:
        return t("status.disk_mount_network", alias=alias, mount=mount,
                 type=str("" if note is None else note))
    if kind == DISK_REFUSAL_MISSING:
        return t("status.disk_mount_missing", alias=alias, mount=mount)
    if kind == DISK_REFUSAL_DEVICE:
        return t("status.disk_device_missing", alias=alias, device=device)
    return ""


# ── The DEVICE choice beside the root (`lsblk -d -n -b -o NAME,SIZE,TYPE`) ──

def parse_lsblk_report(text: str) -> list:
    """The rows of ONE `lsblk -d -n -b -o NAME,SIZE,TYPE` run (PURE).

    Returns `[(name, size, type), …]` with the size as an int and both strings exactly as
    `lsblk` printed them (the NAME is never normalised — it is the kernel's own spelling).
    A section marker, an empty line and every unparsable line are DROPPED, so an `lsblk`
    that is absent, too old or refused (BusyBox, a minimal container) yields `[]` — a
    degradation, never an error. `-d` keeps ONE row per device (no partitions, no holders)
    and `-n` drops the header the parser would otherwise have to skip.
    """
    rows = []
    for line in text.splitlines():
        s = _clean_text(line)
        if not s or s.startswith("---"):
            continue
        parts = s.split(None, 2)
        if len(parts) < 3:
            continue
        name, size_raw, dev_type = parts[0], parts[1], parts[2]
        if not size_raw.isdigit():
            continue
        rows.append((name, int(size_raw), dev_type))
    return rows


def physical_disks(rows) -> list:
    """The PHYSICAL devices of an `lsblk` report — `TYPE == "disk"` (PURE).

    A loop device, a CD-ROM (`rom`), an LVM volume (`dm-*`), a software array (`md*`) and
    every other holder carry their OWN type and are dropped, while a new bus, a new name or
    a new kernel changes nothing: the TYPE is the DECLARATION and the name is not. Answers
    `[(name, size_bytes), …]` and skips a malformed row instead of raising.
    """
    out = []
    for row in rows or ():
        try:
            name, size, dev_type = row
        except (TypeError, ValueError):
            continue
        if str(dev_type).strip().lower() != DISK_TYPE_PHYSICAL:
            continue
        try:
            size = int(size)
        except (TypeError, ValueError):
            continue
        name = str(name).strip()
        if name:
            out.append((name, size))
    return out


def device_label(name, size) -> str:
    """The ONE label of a device — `"sda 9.7 gb"` (PURE).

    The stored LIST, the dialog's combo and the card's tooltip render a device through this
    function, so the three surfaces cannot drift apart. A capacity that cannot be formatted
    (a real zero) leaves the bare name, because a device of unknown size is better named
    than mislabelled.
    """
    figure = bytes_to_gb(size)
    text = str("" if name is None else name).strip()
    return f"{text} {figure}".strip() if figure else text


def device_labels(rows) -> list:
    """The stored LIST of the physical devices — `["sda 9.7 gb", "sdb 100 gb"]` (PURE)."""
    return [device_label(name, size) for name, size in physical_disks(rows)]


def resolve_disk_device(devices, requested) -> dict:
    """The ANSWER of the DEVICE choice, from the devices `lsblk` listed (PURE).

    Returns `{"name", "size", "note"}`. `name` is the REQUEST as the model holds it and is
    EMPTY when the node names no device at all — then the root's `df` figure is the figure
    `disk` carries, exactly as it did before the choice existed (the feature is per-card and
    opt-in). A request the listing HOLDS answers that device's capacity; a request it does
    not hold answers `DISK_NOTE_DEVICE_MISSING` and NO figure — device names are not stable
    (`sdb` becomes `sdc` when a disk is added), so a miss is REPORTED and a card never
    silently shows the number of a disk the user did not name. The match is by NAME and
    case-insensitive: `lsblk` spells the names lower-case, a user may not.
    """
    name = str("" if requested is None else requested).strip()
    if not name:
        return {"name": "", "size": "", "note": ""}
    wanted = name.lower()
    for dev_name, size in physical_disks(devices):
        if dev_name.lower() == wanted:
            return {"name": name, "size": bytes_to_gb(size), "note": ""}
    return {"name": name, "size": "", "note": DISK_NOTE_DEVICE_MISSING}


# ── v1.8.4 (ROADMAP task 3): the INODE fact beside the space figure ──────────────
# Its own section: the six inode columns of `df -i -P` would parse as a `df --output` space row.
# The answer describes the SAME filesystem the mount answer names — 40 % free SPACE beside 100 %
# used INODES is the second lie a card can tell.

def inode_token(value) -> str:
    """A `df -i` "IUse%" cell → the stored token `"100%"` (PURE); `""` — nothing measured.

    `df` prints `-` for a filesystem that has no inode table at all (some pseudo-filesystems),
    and a legacy `df` may print nothing — both answer `""`, which is "not measured" and never
    `"0%"`. A percentage outside 0..100 is refused for the same reason: it cannot be a
    measurement of a table that is at most full.
    """
    text = str("" if value is None else value).strip().rstrip("%").strip()
    if not text.isdigit():
        return ""
    number = int(text)
    return f"{number}%" if 0 <= number <= 100 else ""


def inode_percent(value):
    """The INTEGER percentage of a stored inode token (`"100%"` → 100, PURE); None — not measured."""
    token = inode_token(value)
    return int(token[:-1]) if token else None


def inode_alert(value, threshold: int = INODE_ALERT_PERCENT) -> bool:
    """Is this inode figure at or above the DECLARED alert line? (PURE)

    The ONE predicate behind the card's own line: an exhausted inode table is invisible in the
    free-SPACE figure the card already paints, so the percentage has to be able to speak. An
    unmeasured value (`""`, junk) is never an alert — a missing measurement is not a problem.
    """
    percent = inode_percent(value)
    return percent is not None and percent >= int(threshold)


def parse_inode_report(text: str) -> list:
    """The rows of ONE `df -i -P` run (PURE, v1.8.4).

    Returns `[(source, itotal, iused, ifree, ipcent, target), …]` with the three inode counts as
    ints and the percentage as the machine's own token (`"4%"`). The header line (`Filesystem
    Inodes IUsed IFree IUse% Mounted on`), a section marker and every unparsable line are
    DROPPED, so a `df` that is absent or refuses the flag yields `[]` — a degradation, never an
    error. `df -i` prints `-` in every column of a filesystem that has no inode table at all
    (some pseudo-filesystems): that row is dropped too, because "-" is not a measurement. The
    target is the rest of the line, so a mount point with a space survives.
    """
    rows = []
    for line in text.splitlines():
        s = _clean_text(line)
        if not s or s.startswith("---"):
            continue
        parts = s.split(None, 5)
        if len(parts) < 6:
            continue
        source, itotal, iused, ifree, ipcent, target = parts
        if not (itotal.isdigit() and iused.isdigit() and ifree.isdigit()):
            continue  # the header, or the `-` of a filesystem without an inode table
        token = inode_token(ipcent)
        if not token:
            continue
        rows.append((source, int(itotal), int(iused), int(ifree), token, target))
    return rows


def resolve_inode_answer(rows, mount: str = "") -> str:
    """The inode token of the filesystem an ACCEPTED data mount lives on (PURE, v1.8.4).

    ``mount`` is the mount point the space read really reported (`disk_path`): the row whose
    target IS that path wins. The ROOT row is the fallback — the batch always asks for `/`, so
    it is the one path that is always there — and the single non-root row is the last resort.
    The requested path therefore always answers for the filesystem it is really on.

    An EMPTY ``mount`` answers `""`: the space read refused the request (a path that is not
    there, a network share), so there is no answer for an inode figure to sit beside, and a
    collection that refused the mount CLEARS the stored one instead of leaving a stale number.
    """
    wanted = str("" if mount is None else mount).strip()
    if not wanted:
        return ""
    exact = extra = root = ""
    for row in rows or ():
        try:
            _source, _itotal, _iused, _ifree, token, target = row
        except (TypeError, ValueError):
            continue
        token = inode_token(token)
        if not token:
            continue
        target = str(target).strip()
        if target == wanted:
            exact = exact or token
        elif target == "/":
            root = root or token
        else:
            extra = extra or token
    return exact or root or extra


def parse_info_output(output: str, disk_device: str = "") -> Dict[str, object]:
    """Parse the whole batch output by markers → a dict of finished values.

    Only non-empty values go into the dict; the field format matches the model
    (cpu_cores — as a string, ram/disk — "N gb"). `disk_device` is the node's own
    REQUEST — the device name the card is about — because the answer depends on it.
    """
    sections = {}
    current = None
    for line in output.splitlines():
        line = line.rstrip("\r")
        s = line.strip()
        if s in (_SECTION_OS, _SECTION_CPU, _SECTION_RAM, _SECTION_DISK, _SECTION_DISKS,
                 _SECTION_DISKMOUNT, _SECTION_INODES):
            current = s
            sections[current] = []
        elif s == _SECTION_END:
            break
        elif current is not None:
            sections[current].append(line)

    result: dict = {}

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

    if _SECTION_DISK in sections:
        # The section RAN, so it ANSWERS the root — with a figure or with an explicit "". The
        # difference matters to the ONE write path: a stale figure must never be re-dated by a
        # collection that measured nothing (the `df` family is where it is easiest to see).
        disk = parse_disk_bytes("\n".join(sections[_SECTION_DISK]))
        result["disk_gb"] = bytes_to_gb(disk) if disk else ""

    # The TWO-mount read. The ROOT keeps the figure it ships (`disk_gb`, whose number the inventory's
    # sort key parses) and the DATA-mount pair is the answer the release is about. The family is emitted
    # as ONE unit — path / free / size / note — so the ONE write path can tell "measured" (an answer or a
    # NAMED refusal) from "the collection said nothing about a data mount at all" (a legacy batch, an old
    # fixture): the first WRITES the pair, the second leaves it alone.
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
        # v1.8.4 (ROADMAP task 3): the INODE fact of the filesystem that answer just named. It
        # belongs to the ANSWER (an accepted mount), so a refused one clears it with the pair; a
        # batch WITHOUT the section (a legacy one) says NOTHING and leaves the stored figure alone.
        if _SECTION_INODES in sections:
            result["disk_inodes"] = resolve_inode_answer(
                parse_inode_report("\n".join(sections[_SECTION_INODES])), answer["path"])

    # The DEVICE choice. The section is present in every batch this code builds, so a collection
    # that carries it ANSWERS the request — with a capacity or with a REPORTED miss — while an
    # output without it (a legacy batch, a fixture written before the section existed) says
    # NOTHING about a device and leaves the stored figure and list exactly where they are.
    if _SECTION_DISKS in sections:
        device_rows = parse_lsblk_report("\n".join(sections[_SECTION_DISKS]))
        labels = device_labels(device_rows)
        if labels:
            result["disk_devices"] = labels
        choice = resolve_disk_device(device_rows, disk_device)
        if choice["name"]:
            result["disk_device_note"] = choice["note"]
            if choice["size"]:
                result["disk_gb"] = choice["size"]
            elif "disk_gb" in result:
                del result["disk_gb"]   # the named device vanished: no figure is invented

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
            from services.credential_manager import get_credential_manager, node_scope
            # v1.8rc6 (N50): the ONE connect builder (`AGENTS.md` §4.4) — the branch table, the
            # known-hosts policy and the single `connect()` are shared with the three other sites.
            try:
                from modules.ssh_connect import connect_client
            except ImportError:  # flat layout
                from ssh_connect import connect_client

            final_password = self.password
            if not final_password:
                try:
                    cm = get_credential_manager()
                    final_password = cm.load_password(sid, scope=node_scope(self.data)) or ""
                except Exception:
                    final_password = ""

            # The client is built BEFORE the try so the `finally: client.close()` has one.
            client = paramiko.SSHClient()
            try:
                client, _policy = connect_client(
                    self.data.host, self.data.user, self.data.ssh_port or 22,
                    password=final_password, key_path=self.data.key_path, client=client,
                    timeout=_TIMEOUT_S, banner_timeout=_TIMEOUT_S)

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

            info = parse_info_output(output, getattr(self.data, "disk_device", ""))
            if not info:
                raise RuntimeError("empty system info parsed")
            # An unanswered REQUEST is NOT silence — it travels as a sentence in the collection's own
            # report. The English line below reaches the log file AND the activity ring (the v1.5.2
            # tap); the window composes the translated status-bar sentence from the same note. A
            # share is named by its filesystem type, a vanished device by its own name.
            self._log_disk_note(info)
            self.info_ready.emit(sid, info)
        except Exception as e:  # noqa: BLE001 — any error → a signal, not a crash
            self.info_failed.emit(sid, str(e))

    def _log_disk_note(self, info: dict) -> None:
        """Write the ONE English line of an unanswered REQUEST (never raises).

        Log lines are never translated (the activity panel's own rule), so this is the one
        place a refusal is spelled out for the history: the data MOUNT that is a share or is
        not there, and the DEVICE the listing does not hold. The card's status-bar sentence is
        the window's half of the same fact, composed from the same note by ONE classifier.
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
            if disk_refusal_kind((info or {}).get("disk_device_note")) == DISK_REFUSAL_DEVICE:
                log.info("Device %s was not found on %s — nothing was measured",
                         str(getattr(self.data, "disk_device", "") or "").strip(),
                         self.data.host)
        except Exception:  # noqa: BLE001 — a report is a side channel
            pass

