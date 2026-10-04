# -*- coding: utf-8 -*-
"""The LOCAL file provider of a Commander pane — ONE thread with a FIFO queue over the OS disk.

It answers the SAME method names and signals as `modules/sftp_worker.SftpWorker`, so a pane binds
either provider without branching (LOCAL_PANE.md §1). The read policy, the row shape and the
transfer rules are the SHIPPED ones, imported instead of copied: the four transfer methods are the
LOCAL engine (§5/§6) — `shutil.copy2` through a `.part` + `os.replace`, a move inside one volume and
copy+delete across volumes; every refusal travels as a MACHINE code (`task_payload()`)."""

import logging
import os
import queue
import shutil
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
    from .sftp_worker import (KIND_COPY, KIND_DELETE, KIND_DOWNLOAD, KIND_LIST, KIND_MKDIR,
                              KIND_MOVE, KIND_NORMALIZE, KIND_READ, KIND_RENAME, KIND_UPLOAD,
                              MAX_READ_BYTES, MAX_TREE_DEPTH, MAX_TREE_ENTRIES,
                              PARTIAL_CODE, READ_CAP_NONE, READ_ERROR_BINARY, READ_ERROR_TOO_LARGE,
                              TREE_ERROR_TOO_BIG, classify_extension, is_directory_link,
                              provisional_name, task_payload)
except ImportError:
    from sftp_worker import (KIND_COPY, KIND_DELETE, KIND_DOWNLOAD, KIND_LIST,  # type: ignore
                             KIND_MKDIR, KIND_MOVE, KIND_NORMALIZE, KIND_READ, KIND_RENAME,
                             KIND_UPLOAD, MAX_READ_BYTES, MAX_TREE_DEPTH, MAX_TREE_ENTRIES,
                             PARTIAL_CODE, READ_CAP_NONE, READ_ERROR_BINARY,
                             READ_ERROR_TOO_LARGE, TREE_ERROR_TOO_BIG, classify_extension,
                             is_directory_link, provisional_name, task_payload)

log = get_logger(__name__)

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
    """Internal: a declared refusal of the local surface → its machine code (+ a short detail)."""

    def __init__(self, code: str, error: str = ""):
        super().__init__(code)
        self.code = code
        self.error = str(error or "")


class _LocalRead(Exception):
    """Internal: the SHIPPED read refusal, which travels as a BARE code (the shipped contract)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class _LocalPayload(Exception):
    """Internal: an exception whose own text IS the machine payload of the `task_error`."""

    payload = ""

    def __str__(self):
        return self.payload


class _LocalPartial(_LocalPayload):
    """Internal: a tree stopped in the middle — the SHIPPED `PARTIAL_CODE` payload (§6)."""

    def __init__(self, copied: int, path: str, error: str = ""):
        self.payload = task_payload(PARTIAL_CODE, copied=int(copied), path=str(path),
                                    error=str(error or ""))
        super().__init__(self.payload)


class _LocalTreeTooBig(_LocalPayload):
    """Internal: the walk hit MAX_TREE_ENTRIES / MAX_TREE_DEPTH (the SHIPPED refusal)."""

    def __init__(self):
        self.payload = task_payload(TREE_ERROR_TOO_BIG, limit=MAX_TREE_ENTRIES)
        super().__init__(self.payload)


class _LocalTask:
    """A queue task. `path` is the subject, `path2` the second endpoint (a rename or a transfer
    destination), `is_dir` the kind a delete needs, `max_bytes` the ceiling of a READ task
    (v1.7.5 — `READ_CAP_NONE` keeps the shipped refusal, a positive cap TRUNCATES at it)."""

    __slots__ = ("id", "kind", "label", "path", "path2", "is_dir", "total_size", "max_bytes")

    def __init__(self, task_id: int, kind: str, label: str, path: str = "",
                 path2: str = "", is_dir: bool = False, total_size: int = 0,
                 max_bytes: int = READ_CAP_NONE):
        self.id = task_id
        self.kind = kind
        self.label = label
        self.path = path
        self.path2 = path2
        self.is_dir = bool(is_dir)
        self.total_size = int(total_size or 0)
        self.max_bytes = int(max_bytes or READ_CAP_NONE)


# ── Orphan registry (the `_orphan_workers` pattern of the shipped worker, AGENTS.md §4.8) ──
_orphan_providers: List["LocalFsWorker"] = []


def register_orphan_local_provider(worker: "LocalFsWorker"):
    """Hold a still-running LocalFsWorker until finished() (idempotent).

    The worker is DETACHED from its QObject parent FIRST: it was created under the pane, the
    pane dies with the window, and a parented thread dies with it however firmly this registry
    holds it (AGENTS.md §4.8).
    """
    if worker in _orphan_providers:
        return
    try:
        worker.setParent(None)
    except RuntimeError:
        pass  # the C++ object is already gone
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

    def queue_read(self, path: str, total_size: int = 0,
                   max_bytes: int = READ_CAP_NONE) -> Optional[int]:
        """Read a text file into memory (the SHIPPED policy: the extension, the NULL byte, the cap).

        v1.7.5: `max_bytes` is the SHIPPED task field the pane resolved — a positive cap TRUNCATES
        the read at it, `READ_CAP_NONE` keeps the refusal (the two providers answer the same rule).
        """
        target = str(path or "")
        return self._queue_task(_LocalTask(
            self._next_id, KIND_READ, target, path=target, total_size=total_size,
            max_bytes=max_bytes))

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

    def queue_upload(self, local_path: str, target_dir: str,
                     remote_name: str = "") -> Optional[int]:
        """Copy a local FILE or DIRECTORY into a local directory (the pane's Upload door).

        The name and the signature are the shipped worker's, so the pane's batch needs no branch
        (LOCAL_PANE.md §1): the third argument is the destination name, and a DIRECTORY source is
        carried as a whole tree (LOCAL_PANE.md §6).
        """
        name = remote_name or os.path.basename(str(local_path or ""))
        target = os.path.join(str(target_dir or "") or self.root, name)
        return self._queue_task(_LocalTask(
            self._next_id, KIND_UPLOAD, name, path=str(local_path or ""), path2=target))

    def queue_download(self, path: str, local_dir: str, total_size: int = 0,
                       local_name: str = "") -> Optional[int]:
        """Copy a local FILE or DIRECTORY out into another local directory (the Download door).

        The local pane's "download" reads the OS disk on both ends, so it is the same engine: the
        signature is the shipped worker's and `total_size` is a hint of the caller (the engine
        measures what it really copies).
        """
        name = local_name or os.path.basename(str(path or ""))
        target = os.path.join(str(local_dir or "."), name)
        return self._queue_task(_LocalTask(
            self._next_id, KIND_DOWNLOAD, name, path=str(path or ""), path2=target,
            total_size=int(total_size or 0)))

    def queue_copy(self, source: str, target_dir: str, name: str = "") -> Optional[int]:
        """Copy a local FILE or a whole DIRECTORY TREE into a local directory (§5/§6).

        The destination is `<target_dir>/<name>`, `name` defaulting to the source's basename. Every
        FILE is published atomically (`<target>.part` + `os.replace`) and an existing destination
        directory is MERGED INTO — a copy is additive by construction, never a delete.
        """
        target = os.path.join(str(target_dir or "") or self.root,
                              name or os.path.basename(str(source or "")))
        return self._queue_task(_LocalTask(
            self._next_id, KIND_COPY, os.path.basename(str(source or "")),
            path=str(source or ""), path2=target))

    def queue_move(self, source: str, target_dir: str, name: str = "") -> Optional[int]:
        """Move a local FILE or a whole DIRECTORY TREE into a local directory (§5/§6).

        ONE rename inside a volume (the whole tree when the destination is not there yet), entry by
        entry across volumes, and the emptied source directories removed last, deepest first.
        """
        target = os.path.join(str(target_dir or "") or self.root,
                              name or os.path.basename(str(source or "")))
        return self._queue_task(_LocalTask(
            self._next_id, KIND_MOVE, os.path.basename(str(source or "")),
            path=str(source or ""), path2=target))

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
            except _LocalPayload as e:
                self._emit(self.task_error, task.id, task.kind, str(e))
            except _LocalRefusal as e:
                self._emit(self.task_error, task.id, task.kind, task_payload(e.code, error=e.error))
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
        elif task.kind in (KIND_COPY, KIND_UPLOAD, KIND_DOWNLOAD):
            self._do_copy(task)
        elif task.kind == KIND_MOVE:
            self._do_move(task)
        else:
            raise ValueError("unsupported local task kind: %s" % (task.kind,))

    @staticmethod
    def _detail_of(task: _LocalTask) -> str:
        """The declared `detail` of a finished task: the new directory, the new NAME, the target."""
        if task.kind == KIND_MKDIR:
            return task.path
        if task.kind in (KIND_RENAME, KIND_COPY, KIND_MOVE, KIND_UPLOAD, KIND_DOWNLOAD):
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
        """The SHIPPED read policy, unchanged: the extension, the NULL byte, the cap, 32 KB chunks.

        v1.7.5: the cap is the TASK's — a positive `max_bytes` TRUNCATES the read at exactly that
        many bytes (never a refusal), `READ_CAP_NONE` keeps the shipped `too_large` refusal. The
        rule is the remote worker's, so the two providers cannot drift apart.
        """
        try:
            cap = int(task.max_bytes or READ_CAP_NONE)
        except (TypeError, ValueError):
            cap = READ_CAP_NONE
        truncating = cap > 0
        limit = cap if truncating else MAX_READ_BYTES
        if not truncating and int(task.total_size or 0) > limit:
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
                # A truncating task never asks for a byte beyond its ceiling; an exact task keeps
                # the shipped guard, which trips on the chunk that crosses MAX_READ_BYTES.
                want = CHUNK_SIZE if not truncating else min(CHUNK_SIZE, limit - done)
                if want <= 0:
                    break
                chunk = fh.read(want)
                if not chunk:
                    break
                if not chunks and b"\x00" in chunk:
                    raise _LocalRead(READ_ERROR_BINARY)
                done += len(chunk)
                if not truncating and done > limit:
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
            os.rmdir(task.path)   # ONE empty directory: the tree cleanup belongs to `_move_tree`
        else:
            os.remove(task.path)

    # ── the transfer engine (LOCAL_PANE.md §5/§6) ────────────────────────

    def _do_copy(self, task: _LocalTask):
        """Copy ONE local file — or a whole local TREE — into `task.path2` (§5)."""
        source, target = task.path, task.path2
        self._refuse_symlinked_dir(source)
        if os.path.isdir(source):
            self._copy_tree(task, source, target)
            return
        size = int(os.path.getsize(source) or 0)   # a missing source → the OS's own refusal
        task.total_size = size
        self._copy_file(task, source, target, size, 0)

    def _copy_tree(self, task: _LocalTask, source: str, target: str):
        """The RECURSIVE local copy (§6): the shipped bounds, every file atomic and additive.

        The walk is bounded BEFORE anything is written (one sentence beats a half-copied tree),
        directories are created ahead of their contents, an existing destination directory is
        MERGED INTO (a copy never deletes), and a failure stops the walk with the counters of what
        is already done (`_LocalPartial`). The bytes of the whole tree are ONE progress line.
        """
        entries = self._walk_tree(source)
        task.total_size = sum(size for _path, is_dir, size in entries if not is_dir)
        total = max(1, task.total_size)
        os.makedirs(target, exist_ok=True)
        copied = 0
        done = 0
        for path, is_dir, _size in entries:
            self._check_cancel()
            dest = os.path.join(target, os.path.relpath(path, source))
            if is_dir:
                os.makedirs(dest, exist_ok=True)
                continue
            try:
                done += self._copy_file(task, path, dest, total, done)
            except _LocalCancelled:
                raise
            except Exception as e:   # noqa: BLE001 — one unreadable file must not hide the rest
                raise _LocalPartial(copied, path, str(e)) from e
            copied += 1

    def _copy_file(self, task: _LocalTask, source: str, target: str, total: int,
                   done_base: int) -> int:
        """ONE file of a copy: `shutil.copy2` onto `<target>.part`, then `os.replace` (§5).

        The destination is UNTOUCHED until the very last operation, so an interrupted copy leaves
        it byte-identical and the provisional file is dropped, never left on the disk. A
        destination that is a DIRECTORY is refused — the OS would silently write the file INTO it.
        """
        if os.path.isdir(target):
            raise _LocalRefusal(LOCAL_IS_DIR, os.path.basename(target))
        temp = provisional_name(target, task.id)
        committed = False
        try:
            self._check_cancel()
            shutil.copy2(source, temp)   # keeps the mode and the mtime of the original
            os.replace(temp, target)
            committed = True
        finally:
            if not committed:
                self._remove_quiet(temp)
        size = int(os.path.getsize(target) or 0)
        self._emit(self.progress, task.id, done_base + size, total)
        return size

    def _do_move(self, task: _LocalTask):
        """Move ONE local file — or a whole local TREE — into `task.path2` (§5/§6).

        A file, and a directory whose destination is not there yet, moves in ONE `os.rename` —
        atomic inside a volume — while across volumes the entry-by-entry walk does copy+delete. A
        directory whose destination ALREADY exists is merged into entry by entry, and its emptied
        source directories are removed last, deepest first: a directory that still holds something
        simply STAYS, which the listing then shows.
        """
        source, target = task.path, task.path2
        self._refuse_symlinked_dir(source)
        if os.path.isdir(source):
            if not os.path.exists(target):
                try:
                    os.rename(source, target)
                    task.total_size = 1
                    self._emit(self.progress, task.id, 1, 1)
                    return
                except OSError:
                    pass   # another volume — the walk below is the honest fallback
            self._move_tree(task, source, target)
            return
        size = int(os.path.getsize(source) or 0)   # a missing source → the OS's own refusal
        task.total_size = size
        self._move_file(source, target)
        self._emit(self.progress, task.id, size, size)

    def _move_file(self, source: str, target: str):
        """Move ONE file: `shutil.move` renames inside a volume and copies+deletes across them."""
        if os.path.isdir(target):
            raise _LocalRefusal(LOCAL_IS_DIR, os.path.basename(target))
        self._check_cancel()
        shutil.move(source, target)

    def _move_tree(self, task: _LocalTask, source: str, target: str):
        """The RECURSIVE local move into an EXISTING destination directory (§6).

        The same bounded walk and the same cancel points as the copy: every file moves into place,
        every directory is created on the target when missing, and the SOURCE directories go at the
        end, deepest first. A failure stops the walk with the counters already done.
        """
        entries = self._walk_tree(source)
        task.total_size = len(entries)
        total = max(1, len(entries))
        os.makedirs(target, exist_ok=True)
        moved = 0
        dirs = []
        for index, (path, is_dir, _size) in enumerate(entries):
            self._check_cancel()
            dest = os.path.join(target, os.path.relpath(path, source))
            self._emit(self.progress, task.id, index + 1, total)
            if is_dir:
                dirs.append(path)
                os.makedirs(dest, exist_ok=True)
                continue
            try:
                self._move_file(path, dest)
            except _LocalCancelled:
                raise
            except Exception as e:   # noqa: BLE001 — one refusal must not hide the rest
                raise _LocalPartial(moved, path, str(e)) from e
            moved += 1
        for path in sorted(dirs, key=len, reverse=True):
            self._rmdir_quiet(path)
        self._rmdir_quiet(source)

    @staticmethod
    def _refuse_symlinked_dir(path: str):
        """A directory LINK is never followed (§3/§6) — a Windows junction included (N55)."""
        if is_directory_link(path) and os.path.isdir(path):
            raise _LocalRefusal(LOCAL_SYMLINK_DIR)

    def _walk_tree(self, root: str) -> list:
        """The BOUNDED depth-first walk of one local tree (§6) → pre-order entries.

        Answers `[(path, is_dir, size)]` with a directory ALWAYS before its contents, so a copy can
        create the parent first. Every entry counts against MAX_TREE_ENTRIES and the nesting against
        MAX_TREE_DEPTH — a tree over a bound is refused BEFORE anything is written — and the
        cancellation is checked on every directory. A directory SYMLINK is SKIPPED, never followed;
        a file symlink is listed as the file it is.
        """
        entries: list = []
        self._walk_into(root, 0, entries)
        return entries

    def _walk_into(self, path: str, depth: int, entries: list):
        """One level of `_walk_tree()` — the recursion with the declared bounds.

        `is_directory_link()` sees a Windows JUNCTION (`os.path.islink()` does not) and the
        `os.listdir()` call sits INSIDE the guard (v1.7.5.1, N55): one folder the OS refuses to
        enumerate is SKIPPED, not the end of the whole tree — which is what the per-entry rule
        already promised.
        """
        self._check_cancel()
        if depth > MAX_TREE_DEPTH:
            raise _LocalTreeTooBig()
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
                raise _LocalTreeTooBig()
            if is_dir:
                self._walk_into(full, depth + 1, entries)

    @staticmethod
    def _remove_quiet(path: str) -> bool:
        """Best-effort removal of a PROVISIONAL local path (never masks the real error)."""
        try:
            os.remove(path)
            return True
        except OSError:
            return False

    @staticmethod
    def _rmdir_quiet(path: str) -> bool:
        """Best-effort removal of an EMPTY local directory: one that still holds something stays."""
        try:
            os.rmdir(path)
            return True
        except OSError:
            return False
