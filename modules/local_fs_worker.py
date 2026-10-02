# -*- coding: utf-8 -*-
"""The LOCAL file provider of a Commander pane — ONE thread with a FIFO queue over the OS disk.

It answers the SAME method names and signals as `modules/sftp_worker.SftpWorker`, so a pane binds
either provider without branching (LOCAL_PANE.md §1); the ssh surface it does NOT bind (upload,
download, copy, move) is declared RESERVED for `v1.7.4rc2`. The read policy, the row shape and the
bounds are the SHIPPED ones, imported instead of copied. Every refusal travels as a MACHINE code
(`task_payload()`) — this module holds no UI string, no credential and no network."""

import logging
import os
import queue
import threading
from typing import List, Optional

from PySide6.QtCore import QThread, Signal

try:
    from .logger import get_logger
except ImportError:
    try:
        from modules.logger import get_logger
    except ImportError:  # pragma: no cover — a stripped build logs nowhere
        def get_logger(name):  # noqa: N802 — the same signature
            return logging.getLogger(name)

try:  # the shipped task vocabulary, the read policy and the machine payloads (never copied)
    from .sftp_worker import (KIND_DELETE, KIND_LIST, KIND_MKDIR, KIND_NORMALIZE,
                              KIND_READ, KIND_RENAME, MAX_READ_BYTES, READ_ERROR_BINARY,
                              READ_ERROR_TOO_LARGE, classify_extension, task_payload)
except ImportError:
    from sftp_worker import (KIND_DELETE, KIND_LIST, KIND_MKDIR, KIND_NORMALIZE,  # type: ignore
                             KIND_READ, KIND_RENAME, MAX_READ_BYTES, READ_ERROR_BINARY,
                             READ_ERROR_TOO_LARGE, classify_extension, task_payload)

log = get_logger(__name__)

# The transfer vocabulary of the pane that a local pane deliberately does NOT bind in rc1 —
# `RESERVED_METHODS` is the declaration, `NotImplementedError` is what a caller really gets.
RESERVED_METHODS = ("queue_upload", "queue_download", "queue_copy", "queue_move")

# The read chunk: the shipped 32 KB (one `progress` step per chunk, cancellation between them).
CHUNK_SIZE = 32768

#: How long a pane waits for its local provider before the thread is registered as an ORPHAN —
#: the shipped SFTP budget (a local scan has no network to wait for).
LOCAL_SHUTDOWN_WAIT_MS = 2500

#: The `task_error` KIND of the one NON-task note a local listing can carry: entries that were
#: skipped (an unreadable one, a directory symlink). The listing itself still arrives.
KIND_LIST_PARTIAL = "list_partial"

# task_error payload codes of the local surface (LOCAL_PANE.md §3) — the pane owns the sentence.
LOCAL_PERMISSION = "permission"
LOCAL_LOCKED = "locked"
LOCAL_TOO_LONG = "too_long"
LOCAL_MISSING = "missing"
LOCAL_SYMLINK_DIR = "symlink_dir"
LOCAL_NOT_DIR = "not_dir"
LOCAL_IS_DIR = "is_dir"
LOCAL_EXISTS = "exists"
LOCAL_UNREADABLE = "unreadable"

# A Windows `OSError.winerror` of a file another process holds / a path over the platform limit.
WINERROR_LOCKED = (32, 33)
WINERROR_TOO_LONG = 206
ENAMETOOLONG_ERRNO = 36

# The i18n key of every code, declared ONCE so a new code cannot ship without a sentence.
LOCAL_ERROR_KEYS = {
    LOCAL_PERMISSION: "sftp.local.permission",
    LOCAL_LOCKED: "sftp.local.locked",
    LOCAL_TOO_LONG: "sftp.local.too_long",
    LOCAL_MISSING: "sftp.local.missing",
    LOCAL_SYMLINK_DIR: "sftp.local.symlink_dir",
    LOCAL_NOT_DIR: "sftp.local.not_dir",
    LOCAL_IS_DIR: "sftp.local.is_dir",
    LOCAL_EXISTS: "sftp.local.exists",
    LOCAL_UNREADABLE: "sftp.local.unreadable",
    # the note of a listing that skipped something (never a refusal of the listing itself)
    KIND_LIST_PARTIAL: "sftp.local.skipped",
}

# The i18n key of the SHIPPED read refusals, which travel as a BARE code (not a payload) —
# the pane reads them through `sftp_tab.preview_block_reason()` / `_on_task_error()`.
READ_ERROR_KEYS = {
    READ_ERROR_BINARY: "sftp.viewer.binary",
    READ_ERROR_TOO_LARGE: "sftp.viewer.too_large",
}


def local_error_code(exc) -> str:
    """PURE: the MACHINE code of an `OSError` of the OS disk (LOCAL_PANE.md §3)."""
    winerror = getattr(exc, "winerror", None)
    if isinstance(winerror, int) and WINERROR_TOO_LONG == winerror:
        return LOCAL_TOO_LONG
    if isinstance(winerror, int) and WINERROR_LOCKED == winerror:
        return LOCAL_LOCKED
    if isinstance(exc, PermissionError):
        return LOCAL_PERMISSION
    if isinstance(exc, FileNotFoundError):
        return LOCAL_MISSING
    if isinstance(exc, NotADirectoryError):
        return LOCAL_NOT_DIR
    if isinstance(exc, IsADirectoryError):
        return LOCAL_IS_DIR
    if isinstance(exc, FileExistsError):
        return LOCAL_EXISTS
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == ENAMETOOLONG_ERRNO:
        return LOCAL_TOO_LONG
    return LOCAL_UNREADABLE


def local_error_payload(exc) -> str:
    """`OSError` → the `task_error` payload of the local surface (the OS's own text as the detail)."""
    return task_payload(local_error_code(exc), error=str(exc or ""))


def local_entries(directory: str):
    """`os.scandir` → `(the SHIPPED row dicts, the skipped names)`.

    The row shape is the remote one (`name` / `is_dir` / `size` / `mtime`), sorted the remote
    way (directories first, then case-insensitive by name), so the tree, the "no preview"
    markers, the completer and the walk of `SFTP_PANES.md` render a local listing untouched.
    A directory symlink is SKIPPED rather than followed (LOCAL_PANE.md §3), and an entry the OS
    refuses to stat is skipped too — ONE unreadable entry is a sentence, never an empty pane.
    """
    entries = []
    skipped = []
    with os.scandir(directory) as it:
        for entry in it:
            try:
                is_dir = entry.is_dir()
                if is_dir and entry.is_symlink():
                    skipped.append(entry.name)
                    continue
                if is_dir:
                    entries.append({"name": entry.name, "is_dir": True, "size": 0, "mtime": 0})
                    continue
                info = entry.stat()   # follows a FILE symlink: the OS resolves it
                entries.append({"name": entry.name, "is_dir": False,
                                "size": int(getattr(info, "st_size", 0) or 0),
                                "mtime": int(getattr(info, "st_mtime", 0) or 0)})
            except OSError:
                skipped.append(entry.name)
    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
    return entries, skipped


def local_normalize(path: str, base_dir: str = "") -> str:
    """PURE-ish: the LOCAL resolution of a typed path — `~`, a relative path, a `..`, a slash.

    `~` is expanded through the OS (`expanduser`), a relative path against `base_dir`, and the
    result is normalized the way the OS spells a path. An empty input answers "".
    """
    text = str(path or "").strip()
    if not text:
        return ""
    if text.startswith("~"):
        text = os.path.expanduser(text)
    elif not os.path.isabs(text) and base_dir:
        text = os.path.join(base_dir, text)
    return os.path.normpath(text)


class _LocalCancelled(Exception):
    """Internal: cancel/stop was requested (not an error)."""


class _LocalRefusal(Exception):
    """Internal: a declared refusal of the local surface → its machine code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class _LocalRead(Exception):
    """Internal: the SHIPPED read refusal, which travels as a BARE code (the shipped contract)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class _LocalTask:
    """A queue task. `path` is the subject, `path2` the second endpoint (a rename target),
    `is_dir` the kind a delete needs."""

    __slots__ = ("id", "kind", "label", "path", "path2", "is_dir", "total_size")

    def __init__(self, task_id: int, kind: str, label: str, path: str = "",
                 path2: str = "", is_dir: bool = False, total_size: int = 0):
        self.id = task_id
        self.kind = kind
        self.label = label
        self.path = path
        self.path2 = path2
        self.is_dir = bool(is_dir)
        self.total_size = int(total_size or 0)


# ── Orphan registry (the `_orphan_workers` pattern of the shipped worker, AGENTS.md §4.8) ──
_orphan_providers: List["LocalFsWorker"] = []


def register_orphan_local_provider(worker: "LocalFsWorker"):
    """Hold a still-running LocalFsWorker until finished() (idempotent)."""
    if worker not in _orphan_providers:
        _orphan_providers.append(worker)

        def _drop(_=None, w=worker):
            try:
                _orphan_providers.remove(w)
            except ValueError:
                pass  # already removed (a double finished — does not happen in practice)
        worker.finished.connect(_drop)


class LocalFsWorker(QThread):
    """One worker thread with a task queue over the OS disk (the `SftpWorker` shape)."""

    list_ready = Signal(int, str, list)      # task_id, directory, entries
    task_started = Signal(int, str, str)     # task_id, kind, label
    progress = Signal(int, int, int)         # task_id, done_bytes, total_bytes
    task_done = Signal(int, str)             # task_id, detail
    task_error = Signal(int, str, str)       # task_id, kind, message (a payload for a refusal)
    task_cancelled = Signal(int, str)        # task_id, kind
    read_ready = Signal(int, str, bytes)     # task_id, path, content
    normalize_ready = Signal(int, str, str)  # task_id, requested, resolved path

    def __init__(self, root: str = "", parent=None):
        super().__init__(parent)
        # The name a managed QThread must carry: a bare '' in Qt's abort message is a thread
        # that never went through a constructor (AGENTS.md §4.8).
        self.setObjectName("LocalFsWorker")
        self._root = str(root or "")
        self._queue: "queue.Queue[_LocalTask]" = queue.Queue()
        self._stop_event = threading.Event()
        self._cancel_event = threading.Event()
        self._next_id = 1

    # ── Public API (GUI thread) ──────────────────────────────────────────

    @property
    def root(self) -> str:
        """The directory this provider opens with (the OS home unless the pane says otherwise)."""
        return self._root or os.path.expanduser("~")

    def queue_list(self, directory: str) -> Optional[int]:
        """List a directory. Returns a task id (None — the thread is not running)."""
        target = str(directory or "") or self.root
        return self._queue_task(_LocalTask(self._next_id, KIND_LIST, target, path=target))

    def queue_normalize(self, path: str, base_dir: str = "") -> Optional[int]:
        """Resolve a typed path the LOCAL way (`~`, relative, `..`). Never touches the disk."""
        requested = str(path or "")
        return self._queue_task(_LocalTask(
            self._next_id, KIND_NORMALIZE, requested, path=requested, path2=str(base_dir or "")))

    def queue_read(self, path: str, total_size: int = 0) -> Optional[int]:
        """Read a text file into memory (the SHIPPED policy: the extension, the NULL byte, the cap)."""
        target = str(path or "")
        return self._queue_task(_LocalTask(
            self._next_id, KIND_READ, target, path=target, total_size=total_size))

    def queue_mkdir(self, directory: str, name: str) -> Optional[int]:
        """Create ONE directory inside a directory (the child name is validated by the pane)."""
        target = os.path.join(str(directory or ""), str(name or ""))
        return self._queue_task(_LocalTask(self._next_id, KIND_MKDIR, str(name or ""), path=target))

    def queue_rename(self, path: str, new_name: str) -> Optional[int]:
        """Rename IN PLACE: only the NAME changes, the directory does not."""
        target = os.path.join(os.path.dirname(str(path or "")), str(new_name or ""))
        return self._queue_task(_LocalTask(
            self._next_id, KIND_RENAME, str(new_name or ""), path=str(path or ""), path2=target))

    def queue_delete(self, path: str, is_dir: bool = False) -> Optional[int]:
        """Delete a file, or an EMPTY directory (the shipped `rmdir`, never a recursive delete)."""
        target = str(path or "")
        return self._queue_task(_LocalTask(
            self._next_id, KIND_DELETE, target, path=target, is_dir=is_dir))

    def queue_upload(self, *args, **kwargs) -> Optional[int]:
        """RESERVED for `v1.7.4rc2` (the cross-pane dispatch, LOCAL_PANE.md §5)."""
        raise NotImplementedError(RESERVED_METHODS[0])

    def queue_download(self, *args, **kwargs) -> Optional[int]:
        """RESERVED for `v1.7.4rc2` (the cross-pane dispatch, LOCAL_PANE.md §5)."""
        raise NotImplementedError(RESERVED_METHODS[1])

    def queue_copy(self, *args, **kwargs) -> Optional[int]:
        """RESERVED for `v1.7.4rc2` (the local copy engine, LOCAL_PANE.md §5)."""
        raise NotImplementedError(RESERVED_METHODS[2])

    def queue_move(self, *args, **kwargs) -> Optional[int]:
        """RESERVED for `v1.7.4rc2` (the local move engine, LOCAL_PANE.md §5)."""
        raise NotImplementedError(RESERVED_METHODS[3])

    def cancel(self):
        """Cancel the current operation and everything still queued (the shipped auto-reset)."""
        self._cancel_event.set()

    def shutdown(self, wait_ms: int = 2500):
        """Correct stop: cancel + stop + wait ≤ wait_ms; a stuck thread is an ORPHAN."""
        self._cancel_event.set()
        self._stop_event.set()
        if self.isRunning():
            self.wait(wait_ms)

    def is_cancel_requested(self) -> bool:
        return self._cancel_event.is_set()

    # ── Internal ─────────────────────────────────────────────────────────

    def _queue_task(self, task: _LocalTask) -> Optional[int]:
        # Guarded on isFinished(), NOT isRunning(): a fresh start() has a window where the
        # thread has not begun run() yet, and a task queued there must not be rejected.
        if self.isFinished():
            return None
        self._next_id += 1
        self._queue.put(task)
        return task.id

    def _emit(self, signal, *args):
        """Emit with the teardown guard: a late emit without receivers is a safe no-op."""
        try:
            signal.emit(*args)
        except RuntimeError:
            pass

    def run(self):
        while not self._stop_event.is_set():
            try:
                task = self._queue.get(timeout=0.1)
            except queue.Empty:
                if self._cancel_event.is_set():
                    self._cancel_event.clear()   # nothing was pending — the next task is served
                continue
            if self._cancel_event.is_set():
                self._emit(self.task_cancelled, task.id, task.kind)
                self._apply_cancel()
                continue
            try:
                self._emit(self.task_started, task.id, task.kind, task.label)
                self._run_task(task)
                self._emit(self.task_done, task.id, self._detail_of(task))
            except _LocalCancelled:
                self._emit(self.task_cancelled, task.id, task.kind)
                self._apply_cancel()
            except _LocalRead as e:
                # The SHIPPED read contract: a bare machine code, never a payload.
                self._emit(self.task_error, task.id, task.kind, e.code)
            except _LocalRefusal as e:
                self._emit(self.task_error, task.id, task.kind, task_payload(e.code))
            except Exception as e:  # noqa: BLE001 — a refusal never kills the queue
                self._emit(self.task_error, task.id, task.kind, local_error_payload(e))

    def _run_task(self, task: _LocalTask):
        if task.kind == KIND_LIST:
            self._do_list(task)
        elif task.kind == KIND_NORMALIZE:
            self._do_normalize(task)
        elif task.kind == KIND_READ:
            self._do_read(task)
        elif task.kind == KIND_MKDIR:
            self._do_mkdir(task)
        elif task.kind == KIND_RENAME:
            self._do_rename(task)
        elif task.kind == KIND_DELETE:
            self._do_delete(task)
        else:
            raise ValueError("unsupported local task kind: %s" % (task.kind,))

    @staticmethod
    def _detail_of(task: _LocalTask) -> str:
        """The declared `detail` of a finished task: the new directory, the new name, the subject."""
        if task.kind == KIND_MKDIR:
            return task.path
        if task.kind == KIND_RENAME:
            return task.path2
        return task.path

    def _check_cancel(self):
        if self._cancel_event.is_set():
            raise _LocalCancelled()

    def _apply_cancel(self):
        """Report the queued remainder as cancelled (the flag resets at once — the shipped rule)."""
        self._cancel_event.clear()
        while True:
            try:
                skipped = self._queue.get_nowait()
            except queue.Empty:
                break
            self._emit(self.task_cancelled, skipped.id, skipped.kind)

    def _do_list(self, task: _LocalTask):
        directory = task.path
        if not os.path.isdir(directory):
            raise _LocalRefusal(LOCAL_NOT_DIR if os.path.exists(directory) else LOCAL_MISSING)
        if os.path.islink(directory):
            # A directory symlink is never followed (LOCAL_PANE.md §3): walking it silently can
            # leave the folder the user pointed at.
            raise _LocalRefusal(LOCAL_SYMLINK_DIR)
        entries, skipped = local_entries(directory)
        self._check_cancel()
        self._emit(self.list_ready, task.id, directory, entries)
        if skipped:
            self._emit(self.task_error, task.id, KIND_LIST_PARTIAL,
                       task_payload(KIND_LIST_PARTIAL, count=len(skipped),
                                    names=", ".join(skipped[:5])))

    def _do_normalize(self, task: _LocalTask):
        resolved = local_normalize(task.path, task.path2)
        self._check_cancel()
        self._emit(self.normalize_ready, task.id, task.path, resolved)

    def _do_read(self, task: _LocalTask):
        """The SHIPPED read policy, unchanged: the extension, the NULL byte, the cap, 32 KB chunks."""
        if int(task.total_size or 0) > MAX_READ_BYTES:
            raise _LocalRead(READ_ERROR_TOO_LARGE)
        if classify_extension(task.path) == "binary":
            raise _LocalRead(READ_ERROR_BINARY)
        if os.path.isdir(task.path):
            raise _LocalRefusal(LOCAL_IS_DIR)
        chunks = []
        done = 0
        with open(task.path, "rb") as fh:
            while True:
                self._check_cancel()
                chunk = fh.read(CHUNK_SIZE)
                if not chunk:
                    break
                if not chunks and b"\x00" in chunk:
                    raise _LocalRead(READ_ERROR_BINARY)
                done += len(chunk)
                if done > MAX_READ_BYTES:
                    raise _LocalRead(READ_ERROR_TOO_LARGE)
                chunks.append(chunk)
                self._emit(self.progress, task.id, done, int(task.total_size or 0))
        self._emit(self.read_ready, task.id, task.path, b"".join(chunks))

    def _do_mkdir(self, task: _LocalTask):
        os.mkdir(task.path)   # a refusal (exists / permission / over the limit) is an OSError

    def _do_rename(self, task: _LocalTask):
        if os.path.exists(task.path2) \
                and os.path.normcase(task.path) != os.path.normcase(task.path2):
            raise _LocalRefusal(LOCAL_EXISTS)
        os.rename(task.path, task.path2)

    def _do_delete(self, task: _LocalTask):
        if task.is_dir:
            os.rmdir(task.path)   # NEVER recursive here: a tree delete is rc2's business
        else:
            os.remove(task.path)
