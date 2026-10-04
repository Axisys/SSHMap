# -*- coding: utf-8 -*-
"""The SFTP worker of a terminal session — ONE thread with a FIFO queue over the session's LIVE
transport, driven from the GUI thread only (`queue_*`; the task-id counter is not synchronized).

The client is never touched from another thread (paramiko's `SFTPClient` is not thread-safe): every
call happens in `run()`. The API is the `queue_*` family — list / upload / download / read / mkdir /
rename / delete / normalize plus the Commander's copy and move — and the answers are its signals
(`list_ready`, `task_done`, `task_error`, `read_ready`, `normalize_ready`, …). A refusal and the
copy/move family travel as MACHINE codes/payloads (`READ_ERROR_*`, `task_payload()`), so the tab owns
every sentence and this module holds no UI string and no password. A transfer is ATOMIC
(`<name>.part` + ONE commit — `os.replace` locally, `posix_rename` remotely) and the client is closed
in the `finally` of `run()`; a stuck thread is an ORPHAN, never left to GC (§14f, §60)."""
import json
import logging
import os
import posixpath
import queue
import stat
import threading
from typing import List, Optional

from PySide6.QtCore import QThread, Signal

try:  # v1.5.2: the task records of the activity history (ROADMAP task 2)
    from .logger import get_logger
except ImportError:
    try:
        from modules.logger import get_logger
    except ImportError:  # pragma: no cover — a stripped build logs nowhere
        def get_logger(name):  # noqa: N802 — the same signature
            return logging.getLogger(name)

log = get_logger(__name__)


# Transfer chunk size: 32 KB = paramiko's SFTP_MAX_REQUEST_SIZE — the same size
# as the stock sftp.get/put (equivalent throughput, but full control over
# cancellation and progress between operations).
CHUNK_SIZE = 32 * 1024

KIND_LIST = "list"
KIND_UPLOAD = "upload"
KIND_DOWNLOAD = "download"
KIND_READ = "read"          # v1.3.1: the SFTP viewer — read a text file into memory
KIND_MKDIR = "mkdir"        # v1.3.3.2: the file operations (ROADMAP task 1)
KIND_RENAME = "rename"
KIND_DELETE = "delete"
KIND_NORMALIZE = "normalize"   # v1.6.3: the address bar's path resolution (the server's own)
KIND_COPY = "copy"          # v1.7rc2: the remote→remote copy (a file, or a whole tree)
KIND_MOVE = "move"          # v1.7rc2: the cross-directory move (a file, or a whole tree)

# The operation kinds (no bytes, no progress bar): the page's status line stays
# silent about them — the SFTP tab reports their outcome itself (its message signal).
OP_KINDS = (KIND_MKDIR, KIND_RENAME, KIND_DELETE, KIND_COPY, KIND_MOVE)

# ── v1.5.2 (ROADMAP task 2): the logged family of the activity history ────────
# The TRANSFER and FILE-MANAGER kinds are logged; `list` (navigation) and `read` (the
# viewer opening a file) are not — see the module docstring. The set is declared once,
# so a new kind cannot be forgotten silently: it either joins this tuple or it is a
# navigation kind by an explicit decision.
LOGGED_KINDS = (KIND_UPLOAD, KIND_DOWNLOAD, KIND_MKDIR, KIND_RENAME, KIND_DELETE,
                KIND_COPY, KIND_MOVE)

OUTCOME_DONE = "done"
OUTCOME_FAILED = "failed"
OUTCOME_CANCELLED = "cancelled"

# ── the copy / move family ────────────────────────
# The OpenSSH `copy-data@openssh.com` extension copies a file ON THE SERVER (not a byte crosses the
# wire). paramiko does NOT wrap it, so it is ONE raw extended request on the client; a server that does
# not know the extension answers an error and the chunked stream runs instead. The optional path writes
# the SAME provisional `<target>.part` name and goes through the SAME commit (`AGENTS.md` §4.24).
COPY_DATA_EXTENSION = "copy-data@openssh.com"
SFTP_CMD_EXTENDED = 200     # paramiko's CMD_EXTENDED (paramiko/sftp.py, SFTP v3)

# The bounds of ONE recursive operation — the "bounded walk" of the contract: the
# walk is depth-first and every entry costs a round trip, so a tree over the bound is
# refused with a sentence BEFORE anything is transferred instead of half-copying it.
MAX_TREE_ENTRIES = 5000
MAX_TREE_DEPTH = 32

# task_error payloads of the copy/move family: a MACHINE code with its fields, which
# the tab turns into a translated sentence (the READ_ERROR_* pattern, with the numbers
# the sentence needs). JSON, because a remote path may contain any separator.
PARTIAL_CODE = "partial"                # a TREE stopped in the middle (its counters ride along)
MOVE_ERROR_REFUSED = "move_refused"     # the server refused a cross-directory rename
TREE_ERROR_TOO_BIG = "tree_too_big"     # the walk hit MAX_TREE_ENTRIES / MAX_TREE_DEPTH
NAME_ERROR_UNSAFE = "unsafe_local_name"  # v1.7.5.1 (N40): a server NAME that is local PATH syntax


def task_payload(code: str, **fields) -> str:
    """A task_error payload of the v1.7rc2 family: JSON with the machine `code` (+ fields).

    The worker never composes a UI sentence (§ the module docstring): it names the
    MACHINE reason and the numbers, and the SFTP tab renders the translated line. A field
    whose value is None is dropped, so a payload carries only what it really knows.
    """
    data = {"code": str(code)}
    for key, value in fields.items():
        if value is not None:
            data[key] = value
    try:
        return json.dumps(data, ensure_ascii=False)
    except (TypeError, ValueError):   # a non-serializable field must not break a task
        return json.dumps({"code": str(code)})


def parse_task_payload(message, code: str = ""):
    """`task_payload()` → the dict; None — a plain message, or another code.

    PURE and total: any non-JSON text (a server error, an exception's `str`) answers None,
    so a caller can safely try it on every task_error.
    """
    try:
        data = json.loads(message)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("code"):
        return None
    if code and data.get("code") != code:
        return None
    return data


def payload_log_text(message: str) -> str:
    """The ONE-LINE human rendering of a payload (the activity record); "" otherwise.

    A log is read by a person: the record of a failed tree copy says how far it got and
    where it stopped instead of printing the JSON. PURE, and the only place that knows how
    to spell a payload — `task_log_line()` calls it.
    """
    data = parse_task_payload(message)
    if not data:
        return ""
    code = data.get("code")
    if code == PARTIAL_CODE:
        # A tree stopped by a REFUSED NAME carries that refusal's own payload: it is rendered by
        # THIS function too, so the record names the file and the reason instead of JSON.
        failed = str(data.get("error", "?"))
        return ("partially done: %s file(s) transferred, failed at %s: %s"
                % (data.get("copied", 0), data.get("path", "?"),
                   payload_log_text(failed) or failed))
    if code == MOVE_ERROR_REFUSED:
        return "the server refused the move: %s" % (data.get("error", "?"),)
    if code == TREE_ERROR_TOO_BIG:
        return "the tree exceeds the declared bound (%s entries / depth %s)" % (
            data.get("limit", MAX_TREE_ENTRIES), data.get("depth", MAX_TREE_DEPTH))
    if code == NAME_ERROR_UNSAFE:
        return ("the server's name %s cannot be a file name here (%s)"
                % (data.get("name", "?"), data.get("reason", "?")))
    return json.dumps(data, ensure_ascii=False)


def task_log_line(kind: str, label: str, outcome: str = OUTCOME_DONE, error: str = "",
                  detail: str = ""):
    """The PURE record of one finished SFTP task (v1.5.2) → `(line, level)` or ("", …).

    The topic test pins the sentence without an SFTP server (the topical-test
    convention of the project). `detail` (the task's own final path — the new directory,
    the target file) wins over the short `label` when it is known, so a rename or a
    delete names the whole path a user can act on; a FAILED task usually has no detail
    yet and falls back to the label. A NAVIGATION kind (`list`, `read`) answers an empty
    line: it is not part of the history by the module's own decision. The text carries a
    remote path — never a credential, because this module never holds one.

    v1.7rc2: a copy/move failure whose `error` is a machine PAYLOAD (a partially
    transferred tree, a refused cross-directory rename, a tree over its bound) is recorded
    as the ONE-LINE human rendering of that payload (`payload_log_text`) — the record says
    how far the operation got instead of printing JSON.
    """
    if str(kind) not in LOGGED_KINDS:
        return "", logging.INFO
    text = str(detail or label or "")
    if outcome == OUTCOME_FAILED:
        note = payload_log_text(error)
        return f"SFTP {kind} failed: {text} — {note or error}", logging.ERROR
    if outcome == OUTCOME_CANCELLED:
        return f"SFTP {kind} cancelled: {text}", logging.INFO
    return f"SFTP {kind} finished: {text}", logging.INFO

# v1.3.3.2 (ROADMAP tasks 3 and 6): the provisional name of BOTH transfer directions
# (a local `<dest>.part` committed with os.replace, a remote `<target>.part` renamed
# on success). One constant so the two halves cannot drift apart.
PART_SUFFIX = ".part"


def provisional_token(task_id=None, pid=None) -> str:
    """The WRITER's mark in a provisional name (v1.7.5.1, N53): the process AND the task.

    Without the mark the name is a PURE function of the destination, so a foreign half-written file
    is truncated by the opening write and then DELETED by the failure cleanup — and two writers of
    one target interleave into ONE file. The token makes "which `.part` is mine" a fact.
    """
    return "%d-%s" % (os.getpid() if pid is None else int(pid), task_id)


def provisional_name(target: str, task_id=None, token: str = "") -> str:
    """`<target>.<token>.part` — the provisional name of ONE writer. PURE.

    The SUFFIX stays `PART_SUFFIX` (every reader and every regex knows `.part`); only the middle
    gains the owner, and the commit, the cleanup and the `PARTIAL_CODE` message all read THIS
    helper, so a name can never be cleaned up by an operation that did not create it.
    """
    mark = token or provisional_token(task_id)
    return f"{target}.{mark}{PART_SUFFIX}"


def _open_partial(path: str, mode: int = 0):
    """Open a provisional file for writing, with the CALLER's permission when it asks for one.

    `open(path, "wb")` applies the process umask, and the commit publishes the temporary file's own
    inode, so a caller that must not leave a world-readable copy (the cross-session spool in the
    SHARED OS temp) has to have the file CREATED with its mode — `mode = 0` is the platform default
    and every ordinary transfer keeps the shipped `open()`. On Windows the platform decides.
    """
    if not mode:
        return open(path, "wb")
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, int(mode))
    return os.fdopen(fd, "wb")


# ── v1.7.5.1 (N40): "may this server-offered NAME become a local PATH?" ──────────────────────────
# Windows reads `\ : * ? " < > |`, a trailing dot/space and the reserved DEVICE names as PATH SYNTAX,
# so a hostile remote name walks OUT of the chosen folder or writes somewhere else entirely. The rule
# is PURE with the platform as an ARGUMENT, so a Linux user keeps `report:2024.csv` and `a\b.txt`.
WINDOWS_ILLEGAL_CHARS = '\\/:*?"<>|'
WINDOWS_RESERVED_STEMS = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{i}" for i in range(1, 10)]
    + [f"LPT{i}" for i in range(1, 10)]
)


def local_name_problem(name, windows=None) -> Optional[str]:
    """Why this name must not become a local file name. PURE — the reason, or None.

    Reasons: `empty`, `relative` (`.` / `..`), `characters`, `control` (0x00–0x1F), `reserved` (a
    Windows device name, with or without an extension, any case), `trailing` (a dot or a space).
    """
    if windows is None:
        windows = os.name == "nt"
    text = str(name if name is not None else "")
    if not text:
        return "empty"
    if text in (".", ".."):
        return "relative"
    if windows:
        if any(ch in WINDOWS_ILLEGAL_CHARS for ch in text):
            return "characters"
        if any(ord(ch) < 32 for ch in text):
            return "control"
        stem = text.split(".")[0].rstrip(" .").upper()
        if stem in WINDOWS_RESERVED_STEMS:
            return "reserved"
        if text[-1] in (" ", "."):
            return "trailing"
    else:
        if "/" in text or any(ord(ch) < 32 for ch in text):
            return "characters"
    return None


def local_containment_problem(dest, base) -> Optional[str]:
    """Does `dest` really stay inside `base`? PURE apart from `realpath()` — `outside` when not.

    `startswith()` is NOT this check: `os.path.join(dir, "..\\\\x")` still BEGINS with `dir` while
    the bytes land in its parent. The belt is `os.path.commonpath((realpath(dest), realpath(base)))`
    — it also catches what the name rule cannot see (a symlinked component pointing outside the
    folder) and a cross-drive join, which `commonpath` refuses with `ValueError`.
    """
    try:
        root = os.path.realpath(base or ".")
        target = os.path.realpath(dest)
        if os.path.commonpath((target, root)) != root:
            return "outside"
    except (ValueError, OSError):
        return "outside"
    return None


def local_destination_problem(name, local_dir, windows=None) -> Optional[str]:
    """The name rule PLUS the containment belt for `join(local_dir, name)`. PURE."""
    problem = local_name_problem(name, windows=windows)
    if problem:
        return problem
    return local_containment_problem(os.path.join(local_dir or ".", name), local_dir)


class _SftpNameRefused(Exception):
    """A server-offered NAME that must not become a local PATH (v1.7.5.1, N40).

    The task_error payload names the file and the reason, and the pane renders the translated
    sentence. The refusal is PER FILE: one row of a batch fails alone, and inside a TREE it stops
    that one task through `_SftpPartial`, which carries the counters and this payload with them.
    """

    def __init__(self, name: str, reason: str):
        self.name = str(name or "")
        self.reason = str(reason or "")
        super().__init__(task_payload(NAME_ERROR_UNSAFE, name=self.name, reason=self.reason))


def is_directory_link(path: str) -> bool:
    """Is this path a DIRECTORY that is really a LINK? PURE (v1.7.5.1, N55).

    The contract is "a directory symlink is never followed" — we do not leave the folder the user
    pointed at — and `os.path.islink()` alone does NOT see a Windows JUNCTION: its `lstat` reports
    a plain directory (`S_IFLNK` is not set) while `FILE_ATTRIBUTE_REPARSE_POINT` is. On Python 3.12+
    `os.path.isjunction()` is the portable spelling; on 3.11 the attribute test is the one that
    works. A reparse point IS "a link" for the walk's purpose — the reverse traversal reads the
    junction's TARGET, which is exactly the tree the user did not point at (and, for a MOVE, the
    directories that would then be deleted).

    Everything else (a missing path, a non-directory, an unreadable `lstat`) answers False, so the
    caller keeps the shipped per-entry `except OSError` behaviour.
    """
    try:
        if os.path.islink(path):
            return True
        isjunction = getattr(os.path, "isjunction", None)
        if callable(isjunction):        # Python 3.12+
            return bool(isjunction(path))
        if not hasattr(os, "lstat"):
            return False
        attrs = getattr(os.lstat(path), "st_file_attributes", 0)
        return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    except OSError:
        return False

#: v1.7.5: the DECLARED read policy — the DEFAULT of the `ui_viewer_max_bytes` setting and the point
#: a task with NO cap (`READ_CAP_NONE`) is REFUSED at. A task that carries a positive `max_bytes` is
#: TRUNCATED at that cap instead, and the pane (never the worker) resolves it from the config.
MAX_READ_BYTES = 1024 * 1024

#: The declared "no truncation" cap of a read task — over `MAX_READ_BYTES` it is REFUSED (v1.7.5).
READ_CAP_NONE = 0

# ── v1.3.1 (ROADMAP task 3): the text/binary heuristic ───────────────────────
# The extension lists are a FAST PATH, not the decision: a known-binary extension
# is refused without opening the file, a known-text one (or no extension at all —
# README, Makefile) is read; the real check is the NULL BYTE in the FIRST chunk
# (screens the whole file when the extension lies or is missing).
TEXT_EXTENSIONS = frozenset({
    ".txt", ".text", ".log", ".conf", ".cfg", ".config", ".ini", ".env",
    ".properties", ".py", ".sh", ".bash", ".zsh", ".bat", ".ps1", ".pl",
    ".rb", ".lua", ".json", ".jsonl", ".yml", ".yaml", ".toml", ".xml",
    ".html", ".htm", ".css", ".js", ".ts", ".md", ".rst", ".csv", ".tsv",
    ".sql", ".c", ".h", ".cpp", ".hpp", ".java", ".go", ".rs", ".php",
    ".service", ".timer", ".socket", ".rules", ".list", ".repo", ".key",
    ".pub", ".pem", ".crt", ".patch", ".diff", ".svg",
})
BINARY_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tif", ".tiff",
    ".pdf", ".zip", ".gz", ".tgz", ".bz2", ".xz", ".zst", ".7z", ".rar",
    ".tar", ".exe", ".dll", ".so", ".dylib", ".bin", ".class", ".jar", ".pyc",
    ".pyo", ".o", ".a", ".lib", ".obj", ".iso", ".img", ".deb", ".rpm", ".apk",
    ".msi", ".db", ".sqlite", ".sqlite3", ".mdb", ".mp3", ".mp4", ".avi",
    ".mkv", ".mov", ".wav", ".flac", ".ogg", ".ttf", ".otf", ".woff", ".woff2",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".core", ".dmp",
})

# task_error message codes for "read" (the tab maps them to i18n strings)
READ_ERROR_BINARY = "binary"
READ_ERROR_TOO_LARGE = "too_large"


def classify_extension(name: str) -> str:
    """v1.3.1: the extension heuristic — "text" | "binary" | "unknown".

    The viewer uses only the "binary" answer as a fast refusal; "text" and
    "unknown" files are read and then screened for a null byte. A missing
    extension is "text" (README/Makefile/LICENSE and other extensionless configs).
    """
    base = posixpath.basename(name or "")
    ext = posixpath.splitext(base)[1].lower()
    if ext in TEXT_EXTENSIONS:
        return "text"
    if ext in BINARY_EXTENSIONS:
        return "binary"
    return "text" if not ext else "unknown"


class _SftpCancelled(Exception):
    """Internal: cancel/stop was requested during a transfer (not an error)."""


class _UploadCommitError(Exception):
    """Internal: the upload could not be PUBLISHED (the commit step failed).

    `temp_kept` is True when the destination had ALREADY been removed before the
    failure — the provisional file is then the ONLY copy of the new bytes and must
    survive ("litter beats loss", v1.5rc5 / AUDIT_PENDING N2). It is False when the
    destination never existed or is still intact, where dropping the provisional
    file is correct.
    """

    def __init__(self, message: str, temp_kept: bool = False):
        super().__init__(message)
        self.temp_kept = temp_kept


class _SftpReadError(Exception):
    """Internal: the viewer refused a file (binary / over the limit).

    str(e) is the MACHINE code (READ_ERROR_*) — the task_error payload; the SFTP
    tab turns it into a translated message.
    """
    code = "read_failed"

    def __str__(self):
        return self.code


class _SftpReadBinary(_SftpReadError):
    code = READ_ERROR_BINARY


class _SftpReadTooLarge(_SftpReadError):
    code = READ_ERROR_TOO_LARGE


class _SftpPayloadError(Exception):
    """Internal base of the v1.7rc2 family: `str(e)` is a machine PAYLOAD, not a sentence.

    The task_error message of a copy/move failure is either a plain server error or ONE of
    these payloads; the SFTP tab parses it (`parse_task_payload`) and renders a translated
    sentence, so the worker stays free of UI strings (§ the module docstring).
    """
    code = ""

    def __init__(self, payload: str):
        super().__init__(str(payload))

    def __str__(self):
        return str(self.args[0]) if self.args else self.code


class _SftpPartial(_SftpPayloadError):
    """Internal: a TREE operation stopped in the middle (v1.7rc2).

    The files already published STAY (each of them landed through the atomic single-file
    path): a partially transferred tree is REPORTED, never silent and never rolled back —
    rolling a tree back would delete entries that may have been there before the copy.
    The payload carries how many files were done and where the walk stopped.
    """
    code = PARTIAL_CODE

    def __init__(self, copied: int, path: str, error: str):
        super().__init__(task_payload(PARTIAL_CODE, copied=int(copied), path=str(path),
                                      error=str(error)))


class _SftpMoveRefused(_SftpPayloadError):
    """Internal: the server refused a cross-directory rename (v1.7rc2).

    Raised only when BOTH endpoints are really there — i.e. the refusal is not "one of
    them is missing": the classic cause is two different filesystems (`EXDEV`), which no
    SFTP v3 rename can cross. The payload names the server's own error; the tab renders
    the honest sentence that names the fallback (copy + delete).
    """
    code = MOVE_ERROR_REFUSED

    def __init__(self, error: str):
        super().__init__(task_payload(MOVE_ERROR_REFUSED, error=str(error)))


class _SftpTreeTooBig(_SftpPayloadError):
    """Internal: the walk hit its declared bound (v1.7rc2) — refused BEFORE any transfer."""
    code = TREE_ERROR_TOO_BIG

    def __init__(self):
        super().__init__(task_payload(TREE_ERROR_TOO_BIG, limit=MAX_TREE_ENTRIES,
                                      depth=MAX_TREE_DEPTH))


class _SftpTask:
    """A queue task. remote_path/local_path — the semantics depend on kind:

      list     : remote_path = the directory to list
      upload   : local_path  = the local file, remote_path = the TARGET file
                 (the directory + the name are joined by queue_upload; remote_name=
                 overrides the name — the conflict dialog's "Rename" answer)
      download : remote_path = the remote file, local_path = the TARGET file
                 (local_name= overrides the name of the local copy)
      read     : remote_path = the remote file to read into memory
      mkdir    : remote_path = the directory to create
      rename   : remote_path = the current path, remote_path2 = the new path
      delete   : remote_path = the path, is_dir = a directory (rmdir, not remove)
      copy     : remote_path = the SOURCE, remote_path2 = the destination path
                 (v1.7rc2; total_size is filled by the walk/stat INSIDE the worker)
      move     : remote_path = the SOURCE, remote_path2 = the destination path (v1.7rc2)

    `max_bytes` (v1.7.5) is the CEILING of a "read" task: `READ_CAP_NONE` keeps the shipped
    refusal over `MAX_READ_BYTES`, any positive cap TRUNCATES the read at exactly that many bytes
    (the pane resolved it from the `ui_viewer_max_bytes` setting — the worker reads no config).

    `base_dir` (v1.7.5.1) is the folder the USER chose for a download: the containment belt of the
    name rule needs it, because `os.path.join(local_dir, name)` has already LOST the base by the
    time the task runs (`os.path.dirname(local_path)` of a `..\\x` join is the parent, not the
    chosen folder).

    `part_mode` (v1.7.5.1) is the PERMISSION the provisional file is CREATED with (`0` = the
    platform default). A caller that puts a plaintext copy in the SHARED OS temp asks for the tight
    one, and the mode has to come from the CREATE: `os.replace()` publishes the temporary file's own
    inode, so a mode set on the destination does not survive the commit.
    """
    __slots__ = ("id", "kind", "label", "remote_path", "remote_path2",
                 "local_path", "total_size", "detail", "is_dir", "max_bytes", "base_dir",
                 "part_mode")

    def __init__(self, task_id: int, kind: str, label: str, remote_path: str,
                 local_path: str = "", total_size: int = 0, detail: str = "",
                 remote_path2: str = "", is_dir: bool = False,
                 max_bytes: int = READ_CAP_NONE, base_dir: str = "", part_mode: int = 0):
        self.id = task_id
        self.kind = kind
        self.label = label          # for the GUI (file name / directory path)
        self.remote_path = remote_path
        self.remote_path2 = remote_path2   # the rename target
        self.local_path = local_path
        self.total_size = total_size  # 0 — unknown (indeterminate progress)
        self.detail = detail
        self.is_dir = bool(is_dir)  # delete: rmdir instead of remove
        self.max_bytes = int(max_bytes or READ_CAP_NONE)   # v1.7.5: the viewer's ceiling
        self.base_dir = str(base_dir or "")                # v1.7.5.1: the user's download folder
        self.part_mode = int(part_mode or 0)               # v1.7.5.1: 0 = the platform default


# ── Orphan-worker registry (the _orphan_threads pattern, ssh_terminal.py N4) ───
# The window has WA_DeleteOnClose: if closeEvent did not wait for the worker
# (the network hung, wait() timed out), a thread without a parent must not be
# left to GC. The registry holds it until finished(); it cleans itself up on
# the finished() signal.
_orphan_workers: List["SftpWorker"] = []


def register_orphan_sftp_worker(worker: "SftpWorker"):
    """Hold a still-running SftpWorker until finished() (idempotent)."""
    if worker not in _orphan_workers:
        _orphan_workers.append(worker)

        def _drop(_=None, w=worker):
            try:
                _orphan_workers.remove(w)
            except ValueError:
                pass  # already removed (double finished — does not happen in practice)
        worker.finished.connect(_drop)


class SftpWorker(QThread):
    """One worker thread with a task queue over a live SFTPClient."""

    list_ready = Signal(int, str, list)      # task_id, remote_dir, entries
    task_started = Signal(int, str, str)     # task_id, kind, label
    progress = Signal(int, int, int)         # task_id, done_bytes, total_bytes
    task_done = Signal(int, str)             # task_id, detail
    task_error = Signal(int, str, str)       # task_id, kind, message (READ_ERROR_* for reads)
    task_cancelled = Signal(int, str)        # task_id, kind
    read_ready = Signal(int, str, bytes)     # v1.3.1: task_id, remote_path, content
    normalize_ready = Signal(int, str, str)  # v1.6.3: task_id, requested, resolved path

    def __init__(self, sftp_client, parent=None):
        super().__init__(parent)
        # v1.6.4 (ROADMAP task 1): the managed transfer worker names itself — Qt's abort on a
        # thread destroyed while running names an UNNAMED one as '', and `register_orphan_sftp_worker`
        # above exists to keep THIS class alive until finished(). No behaviour.
        self.setObjectName("SftpWorker")
        self._sftp = sftp_client
        self._queue: "queue.Queue[_SftpTask]" = queue.Queue()
        self._stop_event = threading.Event()
        self._cancel_event = threading.Event()
        self._next_id = 1
        # v1.7rc2: the verdict of the OPTIONAL copy-data@openssh.com feature detection —
        # None = not tried yet, True = the server copied a file this way, False = refused.
        # It is remembered for the life of the worker (one session), so a server without
        # the extension costs ONE refused request and one log line, not one per file.
        self._copy_data_ok = None

    # ── Public API (GUI thread) ──────────────────────────────────────────

    def queue_list(self, remote_dir: str) -> Optional[int]:
        """List a directory. Returns a task id (None — the thread is not running)."""
        return self._queue_task(_SftpTask(
            self._next_id, KIND_LIST, remote_dir, remote_path=remote_dir,
            detail=remote_dir))

    def queue_upload(self, local_path: str, remote_dir: str,
                     remote_name: str = "") -> Optional[int]:
        """Upload a local file — or a whole local DIRECTORY TREE — into a remote directory.

        remote_name — the destination file name (the conflict dialog's "Rename"
        answer); empty = the basename of the local file. The transfer is ATOMIC:
        it lands on `<target>.part` and is renamed on success (v1.3.3.2, task 6).

        A DIRECTORY source is walked on the WORKER thread and carried as a whole
        tree (v1.7.4rc2): the GUI never scans a local folder, and one row stays one
        task — which is what keeps the cross-pane batch bookkeeping per source.
        """
        name = remote_name or os.path.basename(local_path)
        remote_path = posixpath.join(remote_dir or "/", name)
        return self._queue_task(_SftpTask(
            self._next_id, KIND_UPLOAD, name, remote_path=remote_path,
            local_path=local_path, detail=remote_path))

    def queue_download(self, remote_path: str, local_dir: str,
                       total_size: int = 0, local_name: str = "",
                       part_mode: int = 0) -> Optional[int]:
        """Download a remote file into a local directory.

        local_name — the name of the local copy (the conflict dialog's "Rename"
        answer); empty = the basename of the remote file. The transfer is ATOMIC:
        it lands on `<dest>.part` and is committed with os.replace (v1.3.3.2, task 3).

        part_mode — the permission the provisional file is CREATED with (0 = the platform
        default); a caller whose copy must not be readable by others asks for it (v1.7.5.1).

        A remote DIRECTORY is walked on the WORKER thread and received as a whole
        tree (v1.7.4rc2): a folder dropped on the local pane is a folder, exactly as
        the remote pane receives one.
        """
        name = local_name or posixpath.basename(remote_path)
        local_path = os.path.join(local_dir or ".", name)
        return self._queue_task(_SftpTask(
            self._next_id, KIND_DOWNLOAD, name, remote_path=remote_path,
            local_path=local_path, total_size=int(total_size or 0),
            detail=local_path, base_dir=str(local_dir or "."),
            part_mode=int(part_mode or 0)))

    def queue_mkdir(self, remote_dir: str, name: str) -> Optional[int]:
        """v1.3.3.2 (ROADMAP task 1): create a directory under remote_dir.

        The mode is the server's default (paramiko's 0o777 minus the umask, as the
        mkdir command does) — the tab validates the NAME, the server the rest.
        """
        path = posixpath.join(remote_dir or "/", name)
        return self._queue_task(_SftpTask(
            self._next_id, KIND_MKDIR, name, remote_path=path, detail=path))

    def queue_rename(self, remote_path: str, new_name: str) -> Optional[int]:
        """v1.3.3.2: rename a remote file/directory inside its own directory.

        Only the NAME changes — the tab never moves a path across directories
        (that is a "cut/paste" feature, out of the version).
        """
        target = posixpath.join(posixpath.dirname(remote_path) or "/", new_name)
        return self._queue_task(_SftpTask(
            self._next_id, KIND_RENAME, posixpath.basename(remote_path),
            remote_path=remote_path, remote_path2=target, detail=target))

    def queue_delete(self, remote_path: str, is_dir: bool = False) -> Optional[int]:
        """v1.3.3.2: delete a remote file (remove) or a DIRECTORY (rmdir).

        Deliberately not recursive: a non-empty directory reports the server's
        error (recursive transfers are out of v1.3.3.2 — ROADMAP "Not in").
        """
        return self._queue_task(_SftpTask(
            self._next_id, KIND_DELETE, posixpath.basename(remote_path),
            remote_path=remote_path, detail=remote_path, is_dir=bool(is_dir)))

    def queue_read(self, remote_path: str, total_size: int = 0,
                   max_bytes: int = READ_CAP_NONE) -> Optional[int]:
        """v1.3.1 (ROADMAP task 2): read a remote file into memory for the viewer.

        total_size — the size from the listing (0 — unknown): it is only a fast
        path for the limit check; the hard limit is re-checked while reading.
        The content arrives via read_ready(task_id, remote_path, data); a refusal
        (binary / too large) — via task_error with a READ_ERROR_* code.
        v1.5.7: a `~/`-prefixed path is resolved against the server's home inside the
        worker thread (`_expand_home`) — the caller (the command history's "Import from
        the server…") asks for `~/.bash_history` and never touches the network itself.
        v1.7.5: `max_bytes` is the CEILING the caller resolved (the pane's
        `ui_viewer_max_bytes`): the read is TRUNCATED at it, never refused. The default
        `READ_CAP_NONE` keeps the shipped refusal above `MAX_READ_BYTES`.
        """
        return self._queue_task(_SftpTask(
            self._next_id, KIND_READ, posixpath.basename(remote_path),
            remote_path=remote_path, total_size=int(total_size or 0),
            detail=remote_path, max_bytes=max_bytes))

    def queue_copy(self, source: str, target_dir: str, name: str = "") -> Optional[int]:
        """v1.7rc2 (ROADMAP v1.7rc2, task 1): copy a remote FILE or a whole DIRECTORY TREE.

        The destination is `target_dir/name`, `name` defaulting to the source's basename.
        A FILE is streamed through the 32 KB chunk loop into `<target>.part` and published
        by the SAME commit the upload uses (`posix-rename@openssh.com`, or the v3 rename
        with the destination cleared first) — the destination is UNTOUCHED until the very
        last operation, so a cancelled or failed copy leaves it byte-identical. The OpenSSH
        `copy-data` extension is an OPTIONAL fast path (`_try_copy_data`): it writes the
        same provisional name and goes through the same commit, and a server that does not
        answer it is simply streamed. A DIRECTORY is copied RECURSIVELY (the frozen
        addition of rc2 to `SFTP_PANES.md`): a bounded walk, every file atomic, directories
        created as needed and an existing destination directory MERGED INTO — nothing
        inside it is ever deleted. The task's `total_size` is filled INSIDE the worker
        (one `stat` for a file, the sum of the walk for a tree): the GUI thread never
        touches the network.
        """
        target = posixpath.join(target_dir or "/", name or posixpath.basename(source))
        return self._queue_task(_SftpTask(
            self._next_id, KIND_COPY, posixpath.basename(source),
            remote_path=source, remote_path2=target, detail=target))

    def queue_move(self, source: str, target_dir: str, name: str = "") -> Optional[int]:
        """v1.7rc2 (ROADMAP task 2): move a remote file/directory ACROSS directories.

        `SSH_FXP_RENAME` is atomic on ONE filesystem, so a file — and a whole directory
        whose destination does not exist yet — moves in ONE operation. A directory whose
        destination ALREADY exists is moved ENTRY BY ENTRY (a walk of renames; the protocol
        cannot merge two directories in one call), and the emptied source directories are
        removed at the end. A server that refuses the rename although both endpoints exist
        answers the machine code `MOVE_ERROR_REFUSED` — the honest sentence that names the
        fallback (copy + delete), never a traceback. The same-directory rename stays the
        shipped `queue_rename`.
        """
        target = posixpath.join(target_dir or "/", name or posixpath.basename(source))
        return self._queue_task(_SftpTask(
            self._next_id, KIND_MOVE, posixpath.basename(source),
            remote_path=source, remote_path2=target, detail=target))

    def queue_normalize(self, remote_path: str, base_dir: str = "") -> Optional[int]:
        """v1.6.3 (ROADMAP task 4): resolve a typed path THROUGH THE SERVER.

        The address bar of the Files tab hands over exactly what the user typed and never
        resolves it locally: `~` is expanded against the server's home (`_expand_home`, the
        v1.5.7 helper), a RELATIVE path is joined onto `base_dir` (the directory the tab is
        showing), and everything else — `.`/`..`, a symlink, a doubled slash — is answered
        by `SFTPClient.normalize()`, i.e. by the remote's own REALPATH. The answer arrives
        as `normalize_ready(task_id, requested, resolved)`; a path the server cannot resolve
        (missing, no permission) is the ordinary `task_error` — a message, never a traceback.
        """
        path = str(remote_path or "").strip()
        if path and not path.startswith(("/", "~")):
            path = posixpath.join(base_dir or "/", path)
        return self._queue_task(_SftpTask(
            self._next_id, KIND_NORMALIZE, path, remote_path=path, detail=path))

    def cancel(self):
        """Cancel the current transfer and everything still queued.

        The flag is checked between operations (chunk/task); after the queue
        is emptied it auto-resets — new operations work without a repeated
        "unlock".
        """
        self._cancel_event.set()

    def shutdown(self, wait_ms: int = 2500):
        """Correct stop: cancel the current one + stop, wait ≤ wait_ms.

        The SFTPClient is closed in the finally of run() (inside the worker
        thread). If the wait is exhausted (the network hung), the thread stays
        alive — the orphan-worker registry holds it, and the transport's death
        tears the channel down.
        """
        self._cancel_event.set()
        self._stop_event.set()
        if self.isRunning():
            self.wait(wait_ms)

    def is_cancel_requested(self) -> bool:
        return self._cancel_event.is_set()

    # ── Internal ─────────────────────────────────────────────────────────

    def _queue_task(self, task: _SftpTask) -> Optional[int]:
        # Guard on isFinished(), NOT isRunning(): a fresh start() has a window
        # where the thread has not begun run() yet (isRunning() False) —
        # rejecting a task in that moment would leave the tab without a root
        # listing. A finished worker does not accept tasks anymore.
        if self.isFinished():
            return None  # the thread finished — silently ignore
        self._next_id += 1
        self._queue.put(task)
        return task.id

    def _emit(self, signal, *args):
        """Emit with a teardown guard: the receivers' C++ objects may have been
        destroyed (the WA_DeleteOnClose race) — a late emit without receivers
        is a safe no-op, not a RuntimeError."""
        try:
            signal.emit(*args)
        except RuntimeError:
            pass

    def run(self):
        try:
            while not self._stop_event.is_set():
                # Dead transport — nothing to do (the window is closing or the
                # session died; the window drops the worker on finished()).
                try:
                    channel = self._sftp.get_channel()
                except Exception:
                    channel = None
                if channel is not None and getattr(channel, "closed", False):
                    break

                try:
                    task = self._queue.get(timeout=0.1)
                except queue.Empty:
                    # The queue is empty and cancellation was requested (cancel
                    # while idle) — reset the flag: there was nothing to cancel,
                    # new operations work.
                    if self._cancel_event.is_set():
                        self._cancel_event.clear()
                    continue

                if self._cancel_event.is_set():
                    # The task had not started yet — skip it (the GUI learns from
                    # task_cancelled and never waits for it). Cancellation applies
                    # to everything that was in the queue AT THE CLICK MOMENT: the
                    # flag is reset immediately and the rest of the queue contents
                    # is reported.
                    self._emit(self.task_cancelled, task.id, task.kind)
                    self._log_task(task, outcome=OUTCOME_CANCELLED)
                    self._apply_cancel()
                    continue

                try:
                    self._emit(self.task_started, task.id, task.kind, task.label)
                    if task.kind == KIND_LIST:
                        self._do_list(task)
                    elif task.kind == KIND_UPLOAD:
                        self._do_upload(task)
                    elif task.kind == KIND_READ:
                        self._do_read(task)
                    elif task.kind == KIND_NORMALIZE:
                        self._do_normalize(task)
                    elif task.kind == KIND_MKDIR:
                        self._do_mkdir(task)
                    elif task.kind == KIND_RENAME:
                        self._do_rename(task)
                    elif task.kind == KIND_DELETE:
                        self._do_delete(task)
                    elif task.kind == KIND_COPY:
                        self._do_copy(task)
                    elif task.kind == KIND_MOVE:
                        self._do_move(task)
                    else:
                        self._do_download(task)
                    self._emit(self.task_done, task.id, task.detail)
                    self._log_task(task, outcome=OUTCOME_DONE)
                except _SftpCancelled:
                    self._emit(self.task_cancelled, task.id, task.kind)
                    self._log_task(task, outcome=OUTCOME_CANCELLED)
                    self._apply_cancel()
                except Exception as e:  # noqa: BLE001 — path/permission/network error
                    # THE QUEUE DOES NOT DIE: the task reported an error, the
                    # loop continues (ROADMAP task 5 requirement).
                    self._emit(self.task_error, task.id, task.kind, str(e))
                    self._log_task(task, outcome=OUTCOME_FAILED, error=str(e))
        finally:
            try:
                self._sftp.close()
            except Exception:
                pass

    def _log_task(self, task: _SftpTask, outcome: str = OUTCOME_DONE, error: str = ""):
        """v1.5.2 (ROADMAP task 2): ONE record per transfer / file-manager task.

        The line is built by the PURE `task_log_line()` (pinned by the topical test) and
        written from the worker thread: `~/.sshmap/logs/sshmap.log` AND the activity ring
        both take it (`modules/activity_log.py` is thread-safe by design). It is called
        from `run()` only, i.e. never for `list`/`read` — see the module docstring. A
        broken logging setup must never break the queue, hence the guard.
        """
        try:
            line, level = task_log_line(task.kind, task.label, outcome, error, task.detail)
            if line:
                log.log(level, line)
        except Exception:  # noqa: BLE001 — the record is a side channel
            pass

    def _check_cancel(self):
        if self._cancel_event.is_set() or self._stop_event.is_set():
            raise _SftpCancelled()

    def _apply_cancel(self):
        """Reset the cancel flag and report the rest of the queue contents.

        Semantics: cancel applies to everything that was in flight/queued AT THE
        CLICK MOMENT; tasks added AFTER (once the queue was already empty) run
        normally — otherwise "Cancel" of one transfer would also cancel the next
        one queued right after. Called from the worker thread after an
        interrupted/skipped task.
        """
        self._cancel_event.clear()
        while True:
            try:
                skipped = self._queue.get_nowait()
            except queue.Empty:
                break
            self._emit(self.task_cancelled, skipped.id, skipped.kind)

    def _do_list(self, task: _SftpTask):
        entries = []
        for attr in self._sftp.listdir_attr(task.remote_path):
            try:
                is_dir = bool(stat.S_ISDIR(attr.st_mode))
            except (AttributeError, TypeError):
                is_dir = False
            entries.append({
                "name": attr.filename,
                "is_dir": is_dir,
                "size": int(getattr(attr, "st_size", 0) or 0),
                "mtime": int(getattr(attr, "st_mtime", 0) or 0),
            })
        # Directories first, then by name (case-insensitive).
        entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
        self._check_cancel()
        self._emit(self.list_ready, task.id, task.remote_path, entries)

    def _do_upload(self, task: _SftpTask):
        """v1.3.3.2 (task 6): upload to `<target>.part`, then rename it into place — or a TREE.

        An interrupted upload (cancel, a dead network, a full disk) therefore never
        truncates the EXISTING remote file: the destination is untouched until the
        very last operation. The provisional file is dropped on any failure EXCEPT
        the one where the commit already cleared the destination (v1.5rc5, N2): then
        it is the only copy of the new bytes and is KEPT — see `_commit_upload()`.

        v1.7.4rc2: a local DIRECTORY source is carried as a whole tree
        (`_upload_tree`) — the local pane's F5 to a server has to behave like the
        remote F5, because a folder is a folder on either side.
        """
        if self._is_local_dir(task.local_path):
            self._upload_tree(task)
            return
        total = os.path.getsize(task.local_path)  # FileNotFoundError → task_error
        self._upload_file(task, task.local_path, task.remote_path, total, 0)

    @staticmethod
    def _is_local_dir(path: str) -> bool:
        """A LOCAL source that is a directory to walk — a link to one (junction included) is not
        followed (`is_directory_link()`)."""
        try:
            return os.path.isdir(path) and not is_directory_link(path)
        except OSError:
            return False

    def _upload_file(self, task: _SftpTask, local_path: str, target: str,
                     total: int, done_base: int) -> int:
        """ONE file of an upload: the atomic body of v1.3.3.2, reusable by the tree walk.

        `temp` + `_commit_upload()` are the ONE discipline of this direction: the
        destination is untouched until the commit, and a failure that already cleared
        it keeps the provisional file (`_UploadCommitError.temp_kept`).
        """
        temp = provisional_name(target, task.id)
        # open() of a nonexistent directory / no permission → task_error (nothing
        # was created, nothing has to be cleaned up).
        remote_fh = self._sftp.open(temp, "wb")
        committed = False
        keep_temp = False
        try:
            with open(local_path, "rb") as local:
                done = 0
                while True:
                    self._check_cancel()
                    chunk = local.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    remote_fh.write(chunk)
                    done += len(chunk)
                    self._emit(self.progress, task.id, done_base + done, total)
            remote_fh.close()          # close the handle BEFORE the rename
            remote_fh = None
            self._commit_upload(temp, target)
            committed = True
            return done
        except _UploadCommitError as e:
            # The commit failed AFTER the destination was cleared: the .part file
            # is the only surviving copy, so it must not be cleaned up.
            keep_temp = e.temp_kept
            raise
        finally:
            if remote_fh is not None:
                try:
                    remote_fh.close()
                except Exception:
                    pass
            if not committed and not keep_temp:
                self._remote_remove_quiet(temp)   # cancel/failure: no litter, no loss

    def _upload_tree(self, task: _SftpTask):
        """The RECURSIVE upload of one local directory (v1.7.4rc2, LOCAL_PANE.md §6).

        The bounded walk of the LOCAL tree and the rules of the remote copy: directories created
        BEFORE their contents, an existing destination MERGED INTO (a copy is additive by
        construction), every FILE published atomically by `_upload_file`, and a failure reported
        with the counters of what is already done. A directory SYMLINK is never followed, so the
        tree that crosses is the tree the user pointed at.
        """
        entries = self._walk_local_tree(task.local_path)
        task.total_size = sum(size for _path, is_dir, size in entries if not is_dir)
        total = max(1, task.total_size)
        self._ensure_dir(task.remote_path)
        copied = 0
        done = 0
        for path, is_dir, _size in entries:
            self._check_cancel()
            rel = os.path.relpath(path, task.local_path).replace(os.sep, "/")
            dest = posixpath.join(task.remote_path, rel)
            if is_dir:
                self._ensure_dir(dest)
                continue
            try:
                done += self._upload_file(task, path, dest, total, done)
            except _SftpCancelled:
                raise
            except Exception as e:   # noqa: BLE001 — one unreadable file must not hide the rest
                raise _SftpPartial(copied, path, payload_log_text(str(e)) or str(e)) from e
            copied += 1

    def _walk_local_tree(self, root: str) -> list:
        """The BOUNDED depth-first walk of one LOCAL tree (v1.7.4rc2) → pre-order entries.

        The local twin of `_walk_tree`: `[(path, is_dir, size)]` with a directory always before
        its contents, every entry against MAX_TREE_ENTRIES and the nesting against MAX_TREE_DEPTH
        (`_SftpTreeTooBig` BEFORE a byte crosses), the cancellation checked on every directory. A
        directory SYMLINK is SKIPPED — never followed (LOCAL_PANE.md §6) — while a file symlink is
        listed as the file it is.
        """
        entries: list = []
        self._walk_local_into(root, 0, entries)
        return entries

    def _walk_local_into(self, path: str, depth: int, entries: list):
        """One level of `_walk_local_tree()` — the recursion with the declared bounds.

        Two rules (v1.7.5.1, N55): `is_directory_link()` sees a Windows JUNCTION as the link it is
        (`os.path.islink()` does not), and `os.listdir()` sits INSIDE the guard, so ONE folder the OS
        refuses to enumerate is a SKIPPED folder — not the end of the whole tree, which is what the
        docstring above the shipped call already promised per ENTRY.
        """
        self._check_cancel()
        if depth > MAX_TREE_DEPTH:
            raise _SftpTreeTooBig()
        try:
            names = sorted(os.listdir(path))
        except OSError:
            return   # the folder itself is unreadable: skip it, never abort the walk
        for name in names:
            full = os.path.join(path, name)
            try:
                is_dir = os.path.isdir(full)
                if is_dir and is_directory_link(full):
                    continue
                size = 0 if is_dir else os.path.getsize(full)
            except OSError:
                continue   # an entry the OS refuses to read is skipped, never a broken walk
            entries.append((full, is_dir, int(size)))
            if len(entries) > MAX_TREE_ENTRIES:
                raise _SftpTreeTooBig()
            if is_dir:
                self._walk_local_into(full, depth + 1, entries)

    def _commit_upload(self, temp: str, target: str):
        """Publish the finished provisional file as the destination (task 6).

        posix-rename@openssh.com is the atomic overwrite — the extension exists
        exactly for it. A server that refuses it (not OpenSSH / no extension) gets
        the SFTP v3 rename with an existing destination cleared first: a small
        non-atomic window, documented in DOCUMENTATION.md §14f.

        v1.5rc5 (N2): when the retry after that clear fails as well, the old content
        is already gone — so the provisional file is the ONLY copy of the new bytes
        and is KEPT (the caller is told through `_UploadCommitError.temp_kept`),
        with its path named in the message.

        v1.7rc2: a remote→remote COPY publishes through THIS method as well — the
        provisional name and the commit are ONE discipline for the upload and the copy,
        so "the destination is untouched until the last operation" cannot drift between
        the two directions.
        """
        posix_rename = getattr(self._sftp, "posix_rename", None)
        if posix_rename is not None:
            try:
                posix_rename(temp, target)
                return
            except Exception:
                pass   # the extension is unknown to this server — the v3 fallback
        try:
            self._sftp.rename(temp, target)
        except Exception:
            cleared = self._remote_remove_quiet(target)   # the overwrite case only
            try:
                self._sftp.rename(temp, target)
            except Exception as e:
                if cleared:
                    raise _UploadCommitError(
                        "%s (the destination was already replaced; the uploaded "
                        "data is kept at %s)" % (e, temp),
                        temp_kept=True,
                    ) from e
                raise

    def _do_download(self, task: _SftpTask):
        """v1.3.3.2 (task 3): download to `<dest>.part`, commit with os.replace.

        A cancelled or failed download leaves the destination byte-identical to
        what it was; the provisional file is removed (never left on the disk).

        v1.7.4rc2: a remote DIRECTORY source is carried as a whole tree
        (`_download_tree`) — the local pane receives a folder the way the remote
        pane copies one.
        """
        if self._dir_ok(task.remote_path):
            self._download_tree(task)
            return
        self._download_file(task, task.remote_path, task.local_path,
                            int(task.total_size or 0), 0,
                            base_dir=task.base_dir or os.path.dirname(task.local_path),
                            local_name=task.label)

    def _download_file(self, task: _SftpTask, remote_path: str, local_path: str,
                       total: int, done_base: int, base_dir: str = "",
                       local_name: str = "") -> int:
        """ONE file of a download: the atomic body of v1.3.3.2, reusable by the tree walk.

        The LAST MILE of the name rule (v1.7.5.1, N40): this is where `open()` happens, so the name
        (the task's own LABEL — the conflict dialog's "Rename" answer included) and the containment
        belt are checked HERE, before a byte is written — the only gate that cannot be bypassed. The
        provisional file is CREATED with `task.part_mode`, which is what gives a spool its tight mode.
        """
        name = local_name or os.path.basename(local_path)
        problem = local_destination_problem(name, base_dir or os.path.dirname(local_path))
        if problem:
            raise _SftpNameRefused(name, problem)
        remote_fh = self._sftp.open(remote_path, "rb")  # no file → error
        temp = provisional_name(local_path, task.id)
        committed = False
        try:
            with _open_partial(temp, task.part_mode) as local:
                done = 0
                while True:
                    self._check_cancel()
                    chunk = remote_fh.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    local.write(chunk)
                    done += len(chunk)
                    self._emit(self.progress, task.id, done_base + done, total)
                local.flush()
                os.fsync(local.fileno())   # the data on the disk BEFORE the replace
            os.replace(temp, local_path)   # same directory → atomic
            committed = True
            return done
        finally:
            try:
                remote_fh.close()
            except Exception:
                pass
            if not committed:
                try:
                    os.remove(temp)
                except OSError:
                    pass   # never created / already gone — nothing to clean

    def _download_tree(self, task: _SftpTask):
        """The RECURSIVE download of one remote directory (v1.7.4rc2, LOCAL_PANE.md §6).

        The bounded walk of the REMOTE tree and the rules of the remote copy: directories created
        on the OS disk before their contents, an existing destination directory MERGED INTO, every
        FILE published atomically by `_download_file`, and a failure reported with the counters of
        what is already done. The bytes of the whole tree are ONE progress line.

        EVERY per-entry failure — a REFUSED NAME included — leaves through `_SftpPartial`, the ONE
        shape a stopped tree has: the tree is ONE task, so its failure carries how far it got.
        """
        entries = self._walk_tree(task.remote_path)
        task.total_size = sum(size for _path, is_dir, size in entries if not is_dir)
        total = max(1, task.total_size)
        os.makedirs(task.local_path, exist_ok=True)
        copied = 0
        done = 0
        for path, is_dir, _size in entries:
            self._check_cancel()
            rel = posixpath.relpath(path, task.remote_path)
            dest = os.path.join(task.local_path, *rel.split("/"))
            if is_dir:
                # The belt is BEFORE `os.makedirs()`, which would MAKE a hostile `..` chain real
                # (v1.7.5.1, N40). A FILE entry is judged by `_download_file()`'s own authoritative
                # check, so the two never disagree and the name is examined once per entry.
                problem = (local_name_problem(os.path.basename(dest))
                           or local_containment_problem(dest, task.local_path))
                if problem:
                    raise _SftpPartial(copied, path, task_payload(
                        NAME_ERROR_UNSAFE, name=os.path.basename(dest), reason=problem))
                try:
                    os.makedirs(dest, exist_ok=True)
                except OSError as e:
                    raise _SftpPartial(copied, path, str(e)) from e
                continue
            try:
                done += self._download_file(task, path, dest, total, done,
                                            base_dir=task.local_path,
                                            local_name=os.path.basename(dest))
            except _SftpCancelled:
                raise
            except _SftpNameRefused as e:
                # ONE entry's name is the TREE's business, not the batch's: the refusal keeps its
                # machine code INSIDE the partial payload, so the pane can still name it.
                raise _SftpPartial(copied, path, str(e)) from e
            except Exception as e:   # noqa: BLE001 — one refused file must not hide the rest
                raise _SftpPartial(copied, path, str(e)) from e
            copied += 1

    # ── v1.3.3.2: the file operations (ROADMAP task 1) ───────────────────

    def _do_mkdir(self, task: _SftpTask):
        self._sftp.mkdir(task.remote_path)

    def _do_rename(self, task: _SftpTask):
        self._sftp.rename(task.remote_path, task.remote_path2)

    def _do_delete(self, task: _SftpTask):
        if task.is_dir:
            self._sftp.rmdir(task.remote_path)   # non-empty → the server's error
        else:
            self._sftp.remove(task.remote_path)

    def _remote_remove_quiet(self, path: str) -> bool:
        """Best-effort cleanup of a provisional remote path (never masks the real
        error of the task that is already on its way to task_error).

        v1.5rc5 (N2): returns whether the path is really gone — the commit
        step has to know that the destination is gone (an existing caller simply
        ignores the value).
        """
        try:
            self._sftp.remove(path)
            return True
        except Exception:
            return False

    def _remote_rmdir_quiet(self, path: str) -> bool:
        """Best-effort removal of an EMPTY remote directory (v1.7rc2).

        The cleanup of a tree MOVE: a directory that still holds something (a file whose
        rename failed, a file that appeared meanwhile) simply STAYS — the leftover is
        visible in the listing, which is more honest than a silent delete of a non-empty
        directory (the protocol refuses it anyway).
        """
        try:
            self._sftp.rmdir(path)
            return True
        except Exception:
            return False

    # ── v1.7rc2 (ROADMAP v1.7rc2): the copy / move family ────────────────

    def _stat_entry(self, path: str, quiet: bool = False):
        """The SFTPAttributes of ONE remote path (None when `quiet` and unreadable).

        The address bar's `stat` pattern (v1.6.3): the server answers whether the path is
        a file, a directory or nothing at all. `quiet` is for a QUESTION ("is it there?"),
        the default for an OPERATION ("the task must report the server's error").
        """
        stat_fn = getattr(self._sftp, "stat", None)
        if stat_fn is None:
            if quiet:
                return None
            raise IOError("this client cannot stat %s" % (path,))
        try:
            return stat_fn(path)
        except Exception:
            if quiet:
                return None
            raise

    @staticmethod
    def _is_dir(info) -> bool:
        """The SFTPAttributes → "a directory" (a broken/missing mode is not one)."""
        try:
            return stat.S_ISDIR(int(getattr(info, "st_mode", 0) or 0))
        except (TypeError, ValueError):
            return False

    def _dir_ok(self, path: str) -> bool:
        """Is `path` a directory on the server right now? (never raises)"""
        return self._is_dir(self._stat_entry(path, quiet=True))

    def _ensure_dir(self, path: str) -> bool:
        """Create a directory that is not there yet; False when it already IS one.

        ONE round trip for a new directory (the mkdir), two for an existing one (the
        refused mkdir is explained by a `stat`). The SFTP protocol has NO `mkdir -p`, so a
        refused mkdir whose PARENT is missing creates the parent first and retries ONCE —
        a destination root that does not exist yet is an ordinary copy target, not an error.
        A path that exists and is not a directory raises: the caller must never write into
        a file's path as if it were a container.
        """
        try:
            self._sftp.mkdir(path)
            return True
        except Exception as e:
            if self._dir_ok(path):
                return False   # the merge case — the destination directory is kept
            parent = posixpath.dirname(path) or "/"
            if parent != path and not self._dir_ok(parent):
                self._ensure_dir(parent)
                try:
                    self._sftp.mkdir(path)
                    return True
                except Exception as e2:
                    if self._dir_ok(path):
                        return False
                    raise IOError("cannot create the directory %s: %s"
                                  % (path, e2)) from e2
            raise IOError("cannot create the directory %s: %s" % (path, e)) from e

    def _try_copy_data(self, source: str, temp: str) -> bool:
        """The OPTIONAL OpenSSH `copy-data@openssh.com` fast path (v1.7rc2).

        True — the SERVER copied `source` onto the provisional `temp` in ONE request.
        False — the client exposes no raw request, the server does not know the extension,
        or it refused this particular copy: the caller then STREAMS the bytes, and the
        result is identical (the same `.part`, the same commit) — "the fallback is the
        contract, the extension is an optimisation". The verdict is remembered for the
        session, so a server without the extension costs ONE refused request and ONE log
        line instead of one per file.
        """
        if self._copy_data_ok is False:
            return False
        request = getattr(self._sftp, "_request", None)
        if request is None:
            self._copy_data_ok = False
            self._log_copy_data_fallback("the client exposes no raw SFTP request")
            return False
        try:
            # paramiko does not wrap the extension: CMD_EXTENDED + the name + the two paths.
            request(SFTP_CMD_EXTENDED, COPY_DATA_EXTENSION, source, temp)
        except Exception as e:   # noqa: BLE001 — an unknown extension is the normal case
            self._copy_data_ok = False
            self._log_copy_data_fallback(e)
            return False
        self._copy_data_ok = True
        return True

    @staticmethod
    def _log_copy_data_fallback(reason):
        """ONE record when the optional fast path is skipped (the acceptance of v1.7rc2).

        Skipping the extension is not a defect — the stream is the contract — so the line
        is INFO and it never carries a credential (a path may appear in `reason`).
        """
        try:
            log.info("SFTP copy-data@openssh.com is not used (%s) — the chunked stream "
                     "produces the same result", reason)
        except Exception:   # noqa: BLE001 — the record is a side channel
            pass

    def _do_copy(self, task: _SftpTask):
        """v1.7rc2: copy ONE row — a file, or a whole directory tree."""
        source, target = task.remote_path, task.remote_path2
        info = self._stat_entry(source)          # a missing source → task_error
        if self._is_dir(info):
            self._copy_tree(task, source, target)
        else:
            size = int(getattr(info, "st_size", 0) or 0)
            task.total_size = size
            self._copy_file(task, source, target, size=size, total=size)

    def _copy_file(self, task: _SftpTask, source: str, target: str,
                   size: int = 0, done_base: int = 0, total: int = 0) -> int:
        """ONE file, ATOMICALLY: `<target>.part`, then the shipped commit (v1.7rc2).

        Returns the number of bytes copied. The destination is untouched until the very
        last operation: a cancelled or failed copy drops the provisional file (except the
        v1.5rc5/N2 case where the commit already cleared the destination — there the
        provisional file IS the new data and is kept, `_UploadCommitError.temp_kept`).
        `size` is the file's own size; `done_base`/`total` carry the counters of the WHOLE
        operation, so a recursive copy reports ONE monotone progress line.
        """
        size = int(size or 0)
        total = int(total or 0) or size
        temp = provisional_name(target, task.id)
        remote_fh = None
        committed = False
        keep_temp = False
        written = 0
        try:
            self._check_cancel()
            if self._try_copy_data(source, temp):
                written = size
                self._emit(self.progress, task.id, done_base + written, total)
            else:
                # A refused fast path may have left a stub behind — the stream starts from
                # a clean provisional name (open("wb") truncates, but a DIRECTORY named
                # `<target>.part` would not be truncatable at all).
                self._remote_remove_quiet(temp)
                src_fh = self._sftp.open(source, "rb")
                try:
                    remote_fh = self._sftp.open(temp, "wb")
                    while True:
                        self._check_cancel()
                        chunk = src_fh.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        remote_fh.write(chunk)
                        written += len(chunk)
                        self._emit(self.progress, task.id, done_base + written, total)
                finally:
                    try:
                        src_fh.close()
                    except Exception:   # noqa: BLE001 — the write path owns the outcome
                        pass
                remote_fh.close()          # close the handle BEFORE the rename
                remote_fh = None
            self._commit_upload(temp, target)
            committed = True
            return written
        except _UploadCommitError as e:
            # The commit failed AFTER the destination was cleared: the `.part` file is the
            # only surviving copy of the new bytes, so it must not be cleaned up.
            keep_temp = e.temp_kept
            raise
        finally:
            if remote_fh is not None:
                try:
                    remote_fh.close()
                except Exception:   # noqa: BLE001 — a cleanup must never mask the error
                    pass
            if not committed and not keep_temp:
                self._remote_remove_quiet(temp)   # cancel/failure: no litter, no loss

    def _walk_tree(self, root: str) -> list:
        """The BOUNDED depth-first walk of one remote tree (v1.7rc2) → pre-order entries.

        Answers `[(path, is_dir, size)]` with a directory ALWAYS before its contents, so a
        copy can create the parent first. Every entry counts against MAX_TREE_ENTRIES and
        the nesting against MAX_TREE_DEPTH: a tree over a bound raises `_SftpTreeTooBig`
        BEFORE anything is transferred (better one sentence than a half-copied tree). The
        cancellation is checked on every directory, so a Cancel during a huge walk stops
        it. Symlinks are deliberately NOT followed — the SFTP v3 protocol cannot read a
        link target, so a link to a file is copied as that file's CONTENT and a link to a
        directory is refused by the server (a declared limitation of the Commander).
        """
        entries: list = []
        self._walk_into(root, 0, entries)
        return entries

    def _walk_into(self, path: str, depth: int, entries: list):
        """One level of `_walk_tree()` — the recursion with the declared bounds."""
        self._check_cancel()
        if depth > MAX_TREE_DEPTH:
            raise _SftpTreeTooBig()
        for attr in sorted(self._sftp.listdir_attr(path),
                           key=lambda a: str(getattr(a, "filename", ""))):
            name = str(getattr(attr, "filename", ""))
            if name in ("", ".", ".."):
                continue
            full = posixpath.join(path, name)
            is_dir = self._is_dir(attr)
            entries.append((full, is_dir,
                            0 if is_dir else int(getattr(attr, "st_size", 0) or 0)))
            if len(entries) > MAX_TREE_ENTRIES:
                raise _SftpTreeTooBig()
            if is_dir:
                self._walk_into(full, depth + 1, entries)

    def _copy_tree(self, task: _SftpTask, source: str, target: str):
        """The RECURSIVE copy of one directory (v1.7rc2 — the frozen addition to rc2).

        A bounded walk, every FILE published atomically through `_copy_file`, directories
        created BEFORE their contents. An existing destination directory is MERGED INTO —
        nothing inside it is ever deleted, so a copy is additive by construction — and a
        failure stops the walk with the counters of what was already done (`_SftpPartial`:
        "a partially copied tree is reported, never silent"). The bytes of the whole tree
        are ONE progress line.
        """
        entries = self._walk_tree(source)
        task.total_size = sum(size for _path, is_dir, size in entries if not is_dir)
        total = task.total_size
        self._ensure_dir(target)
        done = 0
        copied = 0
        for path, is_dir, _size in entries:
            self._check_cancel()
            dest = posixpath.join(target, posixpath.relpath(path, source))
            if is_dir:
                self._ensure_dir(dest)
                continue
            try:
                done += self._copy_file(task, path, dest, size=_size, done_base=done,
                                        total=total)
            except _SftpCancelled:
                raise
            except _UploadCommitError as e:
                raise _SftpPartial(copied, path, payload_log_text(str(e)) or str(e)) from e
            except Exception as e:   # noqa: BLE001 — one unreadable file must not hide the rest
                raise _SftpPartial(copied, path, str(e)) from e
            copied += 1

    def _do_move(self, task: _SftpTask):
        """v1.7rc2 (ROADMAP task 2): the cross-directory move.

        A file — and a whole directory whose destination does not exist yet — moves in ONE
        atomic rename. A directory whose destination ALREADY exists is moved entry by entry
        (`_move_tree`): the protocol cannot merge two directories in a single call.
        """
        source, target = task.remote_path, task.remote_path2
        info = self._stat_entry(source)          # a missing source → task_error
        if self._is_dir(info) and self._dir_ok(target):
            task.total_size = 1
            self._move_tree(task, source, target)
            return
        task.total_size = int(getattr(info, "st_size", 0) or 0)
        self._rename_into_place(source, target)

    def _rename_into_place(self, source: str, target: str):
        """Publish a MOVE overwriting an existing destination, or refuse honestly (v1.7rc2).

        `posix-rename@openssh.com` is the atomic overwrite (the upload commit's rule); a
        server without it gets the SFTP v3 rename, which REFUSES an existing destination.
        The upload commit's "clear the destination and retry" fallback is deliberately NOT
        used here: a move cannot restore a destination it has cleared, so a move is either
        ATOMIC or it is refused with the machine code `MOVE_ERROR_REFUSED` — the sentence
        that names the fallback (copy + delete) for the user to run by hand.
        """
        first = None
        posix_rename = getattr(self._sftp, "posix_rename", None)
        if posix_rename is not None:
            try:
                posix_rename(source, target)
                return
            except Exception as e:   # noqa: BLE001 — unknown extension OR a real refusal
                first = e
        try:
            self._sftp.rename(source, target)
            return
        except Exception as e:       # noqa: BLE001 — the refusal to classify below
            if first is None:
                first = e
        # Both endpoints really there + a refusal = the cross-device case (no SFTP v3 rename
        # can cross two filesystems). A MISSING endpoint keeps the server's own error.
        if self._dir_ok(posixpath.dirname(target) or "/") \
                and self._stat_entry(source, quiet=True) is not None:
            raise _SftpMoveRefused(str(first)) from first
        raise first

    def _move_tree(self, task: _SftpTask, source: str, target: str):
        """The RECURSIVE move into an EXISTING destination directory (v1.7rc2).

        The same bounded walk and the same cancel points as the copy: every FILE is renamed
        atomically into place, every DIRECTORY is created on the target when missing, and
        the SOURCE directories are removed at the end, deepest first — a directory that
        still holds something simply STAYS (the leftover is visible in the listing). A
        failure stops the walk with the counters already done (`_SftpPartial`).
        """
        entries = self._walk_tree(source)
        task.total_size = len(entries)
        total = max(1, len(entries))
        self._ensure_dir(target)
        moved = 0
        dirs = []
        for index, (path, is_dir, _size) in enumerate(entries):
            self._check_cancel()
            dest = posixpath.join(target, posixpath.relpath(path, source))
            self._emit(self.progress, task.id, index + 1, total)
            if is_dir:
                dirs.append(path)
                self._ensure_dir(dest)
                continue
            try:
                self._rename_into_place(path, dest)
            except _SftpCancelled:
                raise
            except Exception as e:   # noqa: BLE001 — one refusal must not hide the rest
                raise _SftpPartial(moved, path, payload_log_text(str(e)) or str(e)) from e
            moved += 1
        for path in sorted(dirs, key=len, reverse=True):
            self._remote_rmdir_quiet(path)
        self._remote_rmdir_quiet(source)

    def _expand_home(self, path: str) -> str:
        """A `~/`-relative path → an absolute one, resolved ON THIS THREAD (v1.5.7).

        The SFTP protocol has no tilde expansion of its own: the home directory is what the
        server answers to a REALPATH of `.`, and asking for it is a network round trip — so it
        happens HERE, inside the worker thread, never on the GUI thread. A path that does not
        start with `~/` is returned unchanged, and a client whose normalize fails (or answers
        nothing) leaves the path alone: the read then reports the server's own error instead of
        a path this module invented.
        """
        if not isinstance(path, str) or not path.startswith("~/"):
            return path
        try:
            home = self._sftp.normalize(".")
        except Exception:   # noqa: BLE001 — the read reports the failure, not this helper
            return path
        if not home:
            return path
        return posixpath.join(str(home), path[2:])

    def _do_normalize(self, task: _SftpTask):
        """v1.6.3 (ROADMAP task 4): the server's REALPATH of a typed path.

        `~` first (a tilde is not part of the SFTP protocol — `_expand_home` asks the
        server for its home), then `normalize()`. The resolved path is then CHECKED on the
        server (`stat`), because the address bar is a directory bar: a path that does not
        exist and a path that is a FILE both answer `task_error` — a sentence in the tab —
        instead of navigating to a listing that can only fail or showing a file as if it
        were a directory. An empty REALPATH is refused here as well. A client without
        `stat` (a minimal stub) keeps the resolution alone.
        """
        target = self._expand_home(task.remote_path)
        resolved = self._sftp.normalize(target)
        if not resolved:
            raise IOError("the server did not resolve %s" % (target,))
        resolved = str(resolved)
        stat_fn = getattr(self._sftp, "stat", None)
        if stat_fn is not None:
            info = stat_fn(resolved)
            mode = getattr(info, "st_mode", None)
            if mode is not None and not stat.S_ISDIR(mode):
                raise IOError("not a directory: %s" % (resolved,))
        self._emit(self.normalize_ready, task.id, task.remote_path, resolved)

    def _do_read(self, task: _SftpTask):
        """v1.3.1 (ROADMAP task 2): read a text file into memory (the viewer).

        The download pattern (32 KB chunks, cancellation and progress between the
        chunks), but the result is kept in memory and published as read_ready.
        The limit is the TASK's (v1.7.5): a task that carries a `max_bytes` ceiling is TRUNCATED
        at it — the bytes beyond it are never requested and the caller learns how much it got from
        the answer's length — while a task with `READ_CAP_NONE` keeps the shipped refusal (with a
        known size the file is not opened at all, an unknown size trips the guard on the chunk that
        crosses the limit). The null-byte screen runs on the FIRST chunk (a binary file stops after
        one chunk, before anything is decoded or shown).
        v1.5.7: a `~/`-prefixed path is expanded on this thread first (`_expand_home`), so the
        command history can ask for the server's `~/.bash_history`; the ANSWER keeps the path
        the caller asked for, so a panel matches its own task by the name it sent.
        """
        try:
            cap = int(task.max_bytes or READ_CAP_NONE)
        except (TypeError, ValueError):
            cap = READ_CAP_NONE
        truncating = cap > 0
        limit = cap if truncating else MAX_READ_BYTES
        if not truncating and int(task.total_size or 0) > limit:
            raise _SftpReadTooLarge()
        remote_path = self._expand_home(task.remote_path)
        if classify_extension(remote_path) == "binary":
            raise _SftpReadBinary()
        remote_fh = self._sftp.open(remote_path, "rb")  # no file → error
        try:
            chunks = []
            done = 0
            while True:
                self._check_cancel()
                # A truncating task never asks for a byte beyond its ceiling; an exact task keeps
                # the shipped guard, which trips on the chunk that crosses MAX_READ_BYTES.
                want = CHUNK_SIZE if not truncating else min(CHUNK_SIZE, limit - done)
                if want <= 0:
                    break
                chunk = remote_fh.read(want)
                if not chunk:
                    break
                if not chunks and b"\x00" in chunk:
                    raise _SftpReadBinary()
                done += len(chunk)
                if not truncating and done > limit:
                    raise _SftpReadTooLarge()
                chunks.append(chunk)
                self._emit(self.progress, task.id, done, int(task.total_size or 0))
            self._emit(self.read_ready, task.id, task.remote_path, b"".join(chunks))
        finally:
            try:
                remote_fh.close()
            except Exception:
                pass
