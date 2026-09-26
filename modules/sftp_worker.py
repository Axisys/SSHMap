# -*- coding: utf-8 -*-
"""SFTP worker thread of the terminal window (v1.1.3, ROADMAP task 1).

One worker thread per session with a FIFO task queue
(list/upload/download/read + the v1.3.3.2 file operations mkdir/rename/delete):
the paramiko SFTPClient does NOT guarantee thread-safety — all operations on
the client are performed strictly in this thread; N threads for one client are
forbidden. The window opens the client on top of a live transport
(`terminal_thread.client.open_sftp()`) — without a second authentication and a
second known_hosts pass (ROADMAP task 3); the transport serves the terminal
channel at the same time — this is paramiko's standard mode (different channels
of one Transport, the transport's internal locks).

Cancellation: a flag (_cancel_event), checked BETWEEN operations — before each
transfer chunk and before starting each task from the queue. A cancelled
transfer stops at the nearest chunk; the tasks left in the queue are skipped
with a task_cancelled signal (the GUI state is driven by signals only). The
flag auto-resets when the queue is empty — subsequent operations work.

Correct shutdown: stop_event + cancel_event + wait(); the SFTPClient is closed
in the finally of run() INSIDE the worker thread (the channel is not closed
from a foreign thread with requests in flight). If the window closed while a
transfer is stuck on a dead network (closeEvent waits a bounded time), the
thread keeps living: the transport's death (the terminal client.close() in the
terminal thread's finally) tears the SFTP channel down, the operation fails
with an exception → except → stop. The orphan-worker registry
(_orphan_workers, the _orphan_threads pattern from ssh_terminal.py v1.1.2RC1
N4) holds such a thread until finished() — a QThread without a QObject parent
must not be left to GC ("QThread: Destroyed while thread is still running");
all of the window's slots are disconnected in closeEvent, late emits without
receivers — a safe no-op (Qt itself removes connections to a destroyed
C++ object).

Signals (emitted from the worker thread; delivery to the GUI — queued):
    list_ready(task_id, remote_dir, entries)  — entries: [{name,is_dir,size,mtime}]
                                                (directories first, then by name)
    task_started(task_id, kind, label)        — kind: "list" | "upload" | "download"
                                                | "read" | "mkdir" | "rename" | "delete"
                                                | "normalize"
    progress(task_id, done_bytes, total_bytes)
    task_done(task_id, detail)                — detail: final path (file/directory)
    task_error(task_id, kind, message)        — task error; the QUEUE does NOT die
    task_cancelled(task_id, kind)             — cancellation (not an error)
    read_ready(task_id, remote_path, data)    — v1.3.1: the viewer's file content (bytes)
    normalize_ready(task_id, requested, resolved) — v1.6.3: the address bar's path,
                                                resolved by the SERVER (REALPATH)

For a "read" task the task_error message is a MACHINE CODE (READ_ERROR_*), not a
human sentence: the SFTP tab maps it to an i18n message (the worker stays free of
UI strings). Everything else reports str(exception) as before.

The transfer ATOMICITY (v1.3.3.2, ROADMAP tasks 3 and 6): both directions write to a
provisional PART_SUFFIX name and commit the result in ONE step — the local side with
os.replace (the tmp + fsync + replace discipline every other write path of the
application uses), the remote side with posix_rename (posix-rename@openssh.com, the
extension that exists exactly for the atomic overwrite) and, on a server that does not
know it, with a v3 rename that clears an existing destination first (a small
non-atomic window — DOCUMENTATION.md §14f). A cancelled or failed transfer therefore
never truncates the destination: the old file stays byte-identical, the provisional
file is dropped — EXCEPT in the one case where the commit already cleared the
destination and the retry failed as well (v1.5rc5, N2): the provisional file is then
the only copy of the new bytes and is KEPT, with its path named in the error.

The queue_mkdir / queue_rename / queue_delete kinds (v1.3.3.2, ROADMAP task 1) share
the same queue and the same rule: the client stays single-threaded, a failing
operation reports task_error, and the QUEUE DOES NOT DIE (the v1.1.3 rule). A
directory delete is NOT recursive (rmdir — a non-empty directory reports the server's
error); recursive transfers are out of the version.

v1.5.2 (ROADMAP task 2): the worker logged NOTHING — a failed transfer existed only as a
progress line that vanished with the tab. Every task of the TRANSFER / FILE-MANAGER
family (upload, download, mkdir, rename, delete) now leaves ONE record when it finishes,
fails or is cancelled, and it reaches both `sshmap.log` and the activity panel. `list`
(a directory listing) and `read` (the viewer opening a file) are deliberately NOT logged:
they are navigation, and they happen on every click — a history of them would drown the
facts a user opens the panel for. The record carries the task's own LABEL (a path), never
a credential: this module never holds a password.

The queue_* methods are intended to be called from the GUI thread (the task id
counter is not synchronized — all calls come from a single thread).
"""
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

# The operation kinds (no bytes, no progress bar): the page's status line stays
# silent about them — the SFTP tab reports their outcome itself (its message signal).
OP_KINDS = (KIND_MKDIR, KIND_RENAME, KIND_DELETE)

# ── v1.5.2 (ROADMAP task 2): the logged family of the activity history ────────
# The TRANSFER and FILE-MANAGER kinds are logged; `list` (navigation) and `read` (the
# viewer opening a file) are not — see the module docstring. The set is declared once,
# so a new kind cannot be forgotten silently: it either joins this tuple or it is a
# navigation kind by an explicit decision.
LOGGED_KINDS = (KIND_UPLOAD, KIND_DOWNLOAD, KIND_MKDIR, KIND_RENAME, KIND_DELETE)

OUTCOME_DONE = "done"
OUTCOME_FAILED = "failed"
OUTCOME_CANCELLED = "cancelled"


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
    """
    if str(kind) not in LOGGED_KINDS:
        return "", logging.INFO
    text = str(detail or label or "")
    if outcome == OUTCOME_FAILED:
        return f"SFTP {kind} failed: {text} — {error}", logging.ERROR
    if outcome == OUTCOME_CANCELLED:
        return f"SFTP {kind} cancelled: {text}", logging.INFO
    return f"SFTP {kind} finished: {text}", logging.INFO

# v1.3.3.2 (ROADMAP tasks 3 and 6): the provisional name of BOTH transfer directions
# (a local `<dest>.part` committed with os.replace, a remote `<target>.part` renamed
# on success). One constant so the two halves cannot drift apart.
PART_SUFFIX = ".part"

# ── v1.3.1 (ROADMAP task 2): the viewer's hard limit ─────────────────────────
# A larger file is NOT read at all (not even partially): the task fails with
# task_error(READ_ERROR_TOO_LARGE) at the very start when the size is known from
# the listing, and mid-read when the size was unknown (the guard is checked on
# every chunk, so at most one chunk beyond the limit is ever requested).
MAX_READ_BYTES = 1024 * 1024

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
    """
    __slots__ = ("id", "kind", "label", "remote_path", "remote_path2",
                 "local_path", "total_size", "detail", "is_dir")

    def __init__(self, task_id: int, kind: str, label: str, remote_path: str,
                 local_path: str = "", total_size: int = 0, detail: str = "",
                 remote_path2: str = "", is_dir: bool = False):
        self.id = task_id
        self.kind = kind
        self.label = label          # for the GUI (file name / directory path)
        self.remote_path = remote_path
        self.remote_path2 = remote_path2   # the rename target
        self.local_path = local_path
        self.total_size = total_size  # 0 — unknown (indeterminate progress)
        self.detail = detail
        self.is_dir = bool(is_dir)  # delete: rmdir instead of remove


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

    # ── Public API (GUI thread) ──────────────────────────────────────────

    def queue_list(self, remote_dir: str) -> Optional[int]:
        """List a directory. Returns a task id (None — the thread is not running)."""
        return self._queue_task(_SftpTask(
            self._next_id, KIND_LIST, remote_dir, remote_path=remote_dir,
            detail=remote_dir))

    def queue_upload(self, local_path: str, remote_dir: str,
                     remote_name: str = "") -> Optional[int]:
        """Upload a local file into a remote directory.

        remote_name — the destination file name (the conflict dialog's "Rename"
        answer); empty = the basename of the local file. The transfer is ATOMIC:
        it lands on `<target>.part` and is renamed on success (v1.3.3.2, task 6).
        """
        name = remote_name or os.path.basename(local_path)
        remote_path = posixpath.join(remote_dir or "/", name)
        return self._queue_task(_SftpTask(
            self._next_id, KIND_UPLOAD, name, remote_path=remote_path,
            local_path=local_path, detail=remote_path))

    def queue_download(self, remote_path: str, local_dir: str,
                       total_size: int = 0, local_name: str = "") -> Optional[int]:
        """Download a remote file into a local directory.

        local_name — the name of the local copy (the conflict dialog's "Rename"
        answer); empty = the basename of the remote file. The transfer is ATOMIC:
        it lands on `<dest>.part` and is committed with os.replace (v1.3.3.2, task 3).
        """
        name = local_name or posixpath.basename(remote_path)
        local_path = os.path.join(local_dir or ".", name)
        return self._queue_task(_SftpTask(
            self._next_id, KIND_DOWNLOAD, name, remote_path=remote_path,
            local_path=local_path, total_size=int(total_size or 0),
            detail=local_path))

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

    def queue_read(self, remote_path: str, total_size: int = 0) -> Optional[int]:
        """v1.3.1 (ROADMAP task 2): read a remote file into memory for the viewer.

        total_size — the size from the listing (0 — unknown): it is only a fast
        path for the limit check; the hard limit is re-checked while reading.
        The content arrives via read_ready(task_id, remote_path, data); a refusal
        (binary / too large) — via task_error with a READ_ERROR_* code.
        v1.5.7: a `~/`-prefixed path is resolved against the server's home inside the
        worker thread (`_expand_home`) — the caller (the command history's "Import from
        the server…") asks for `~/.bash_history` and never touches the network itself.
        """
        return self._queue_task(_SftpTask(
            self._next_id, KIND_READ, posixpath.basename(remote_path),
            remote_path=remote_path, total_size=int(total_size or 0),
            detail=remote_path))

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
        """v1.3.3.2 (task 6): upload to `<target>.part`, then rename it into place.

        An interrupted upload (cancel, a dead network, a full disk) therefore never
        truncates the EXISTING remote file: the destination is untouched until the
        very last operation. The provisional file is dropped on any failure EXCEPT
        the one where the commit already cleared the destination (v1.5rc5, N2): then
        it is the only copy of the new bytes and is KEPT — see `_commit_upload()`.
        """
        total = os.path.getsize(task.local_path)  # FileNotFoundError → task_error
        temp = task.remote_path + PART_SUFFIX
        # open() of a nonexistent directory / no permission → task_error (nothing
        # was created, nothing has to be cleaned up).
        remote_fh = self._sftp.open(temp, "wb")
        committed = False
        keep_temp = False
        try:
            with open(task.local_path, "rb") as local:
                done = 0
                while True:
                    self._check_cancel()
                    chunk = local.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    remote_fh.write(chunk)
                    done += len(chunk)
                    self._emit(self.progress, task.id, done, total)
            remote_fh.close()          # close the handle BEFORE the rename
            remote_fh = None
            self._commit_upload(temp, task.remote_path)
            committed = True
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
        """
        remote_fh = self._sftp.open(task.remote_path, "rb")  # no file → error
        temp = task.local_path + PART_SUFFIX
        committed = False
        try:
            with open(temp, "wb") as local:
                done = 0
                while True:
                    self._check_cancel()
                    chunk = remote_fh.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    local.write(chunk)
                    done += len(chunk)
                    self._emit(self.progress, task.id, done, task.total_size)
                local.flush()
                os.fsync(local.fileno())   # the data on the disk BEFORE the replace
            os.replace(temp, task.local_path)   # same directory → atomic
            committed = True
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

        v1.5rc5 (N2): returns whether the path was actually REMOVED — the commit
        step has to know that the destination is gone (an existing caller simply
        ignores the value).
        """
        try:
            self._sftp.remove(path)
            return True
        except Exception:
            return False

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
        A hard limit MAX_READ_BYTES: a larger file is not read AT ALL — when the
        size is known from the listing the task is refused before opening it, and
        an unknown size trips the guard on the chunk that crosses the limit.
        The null-byte screen runs on the FIRST chunk (a binary file stops after
        one chunk, before anything is decoded or shown).
        v1.5.7: a `~/`-prefixed path is expanded on this thread first (`_expand_home`), so the
        command history can ask for the server's `~/.bash_history`; the ANSWER keeps the path
        the caller asked for, so a panel matches its own task by the name it sent.
        """
        if int(task.total_size or 0) > MAX_READ_BYTES:
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
                chunk = remote_fh.read(CHUNK_SIZE)
                if not chunk:
                    break
                if not chunks and b"\x00" in chunk:
                    raise _SftpReadBinary()
                done += len(chunk)
                if done > MAX_READ_BYTES:
                    raise _SftpReadTooLarge()
                chunks.append(chunk)
                self._emit(self.progress, task.id, done, int(task.total_size or 0))
            self._emit(self.read_ready, task.id, task.remote_path, b"".join(chunks))
        finally:
            try:
                remote_fh.close()
            except Exception:
                pass
