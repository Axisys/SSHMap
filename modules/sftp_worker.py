# -*- coding: utf-8 -*-
"""SFTP worker thread of the terminal window (v1.1.3, ROADMAP task 1).

One worker thread per session with a FIFO task queue (list/upload/download/read):
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
    task_started(task_id, kind, label)        — kind: "list" | "upload" | "download" | "read"
    progress(task_id, done_bytes, total_bytes)
    task_done(task_id, detail)                — detail: final path (file/directory)
    task_error(task_id, kind, message)        — task error; the QUEUE does NOT die
    task_cancelled(task_id, kind)             — cancellation (not an error)
    read_ready(task_id, remote_path, data)    — v1.3.1: the viewer's file content (bytes)

For a "read" task the task_error message is a MACHINE CODE (READ_ERROR_*), not a
human sentence: the SFTP tab maps it to an i18n message (the worker stays free of
UI strings). Everything else reports str(exception) as before.

The queue_* methods are intended to be called from the GUI thread (the task id
counter is not synchronized — all calls come from a single thread).
"""
import os
import posixpath
import queue
import stat
import threading
from typing import List, Optional

from PySide6.QtCore import QThread, Signal


# Transfer chunk size: 32 KB = paramiko's SFTP_MAX_REQUEST_SIZE — the same size
# as the stock sftp.get/put (equivalent throughput, but full control over
# cancellation and progress between operations).
CHUNK_SIZE = 32 * 1024

KIND_LIST = "list"
KIND_UPLOAD = "upload"
KIND_DOWNLOAD = "download"
KIND_READ = "read"          # v1.3.1: the SFTP viewer — read a text file into memory

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
      upload   : local_path  = the local file, remote_path = the TARGET directory
      download : remote_path = the remote file, local_path = the target directory
    """
    __slots__ = ("id", "kind", "label", "remote_path", "local_path",
                 "total_size", "detail")

    def __init__(self, task_id: int, kind: str, label: str, remote_path: str,
                 local_path: str = "", total_size: int = 0, detail: str = ""):
        self.id = task_id
        self.kind = kind
        self.label = label          # for the GUI (file name / directory path)
        self.remote_path = remote_path
        self.local_path = local_path
        self.total_size = total_size  # 0 — unknown (indeterminate progress)
        self.detail = detail


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

    def __init__(self, sftp_client, parent=None):
        super().__init__(parent)
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

    def queue_upload(self, local_path: str, remote_dir: str) -> Optional[int]:
        """Upload a local file into a remote directory (name = basename)."""
        name = os.path.basename(local_path)
        remote_path = posixpath.join(remote_dir or "/", name)
        return self._queue_task(_SftpTask(
            self._next_id, KIND_UPLOAD, name, remote_path=remote_path,
            local_path=local_path, detail=remote_path))

    def queue_download(self, remote_path: str, local_dir: str,
                       total_size: int = 0) -> Optional[int]:
        """Download a remote file into a local directory (name = basename)."""
        name = posixpath.basename(remote_path)
        local_path = os.path.join(local_dir or ".", name)
        return self._queue_task(_SftpTask(
            self._next_id, KIND_DOWNLOAD, name, remote_path=remote_path,
            local_path=local_path, total_size=int(total_size or 0),
            detail=local_path))

    def queue_read(self, remote_path: str, total_size: int = 0) -> Optional[int]:
        """v1.3.1 (ROADMAP task 2): read a remote file into memory for the viewer.

        total_size — the size from the listing (0 — unknown): it is only a fast
        path for the limit check; the hard limit is re-checked while reading.
        The content arrives via read_ready(task_id, remote_path, data); a refusal
        (binary / too large) — via task_error with a READ_ERROR_* code.
        """
        return self._queue_task(_SftpTask(
            self._next_id, KIND_READ, posixpath.basename(remote_path),
            remote_path=remote_path, total_size=int(total_size or 0),
            detail=remote_path))

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
                    else:
                        self._do_download(task)
                    self._emit(self.task_done, task.id, task.detail)
                except _SftpCancelled:
                    self._emit(self.task_cancelled, task.id, task.kind)
                    self._apply_cancel()
                except Exception as e:  # noqa: BLE001 — path/permission/network error
                    # THE QUEUE DOES NOT DIE: the task reported an error, the
                    # loop continues (ROADMAP task 5 requirement).
                    self._emit(self.task_error, task.id, task.kind, str(e))
        finally:
            try:
                self._sftp.close()
            except Exception:
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
        total = os.path.getsize(task.local_path)  # FileNotFoundError → task_error
        remote_fh = self._sftp.open(task.remote_path, "wb")
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
        finally:
            try:
                remote_fh.close()
            except Exception:
                pass

    def _do_download(self, task: _SftpTask):
        remote_fh = self._sftp.open(task.remote_path, "rb")  # no file → error
        try:
            with open(task.local_path, "wb") as local:
                done = 0
                while True:
                    self._check_cancel()
                    chunk = remote_fh.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    local.write(chunk)
                    done += len(chunk)
                    self._emit(self.progress, task.id, done, task.total_size)
        finally:
            try:
                remote_fh.close()
            except Exception:
                pass

    def _do_read(self, task: _SftpTask):
        """v1.3.1 (ROADMAP task 2): read a text file into memory (the viewer).

        The download pattern (32 KB chunks, cancellation and progress between the
        chunks), but the result is kept in memory and published as read_ready.
        A hard limit MAX_READ_BYTES: a larger file is not read AT ALL — when the
        size is known from the listing the task is refused before opening it, and
        an unknown size trips the guard on the chunk that crosses the limit.
        The null-byte screen runs on the FIRST chunk (a binary file stops after
        one chunk, before anything is decoded or shown).
        """
        if int(task.total_size or 0) > MAX_READ_BYTES:
            raise _SftpReadTooLarge()
        if classify_extension(task.remote_path) == "binary":
            raise _SftpReadBinary()
        remote_fh = self._sftp.open(task.remote_path, "rb")  # no file → error
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
