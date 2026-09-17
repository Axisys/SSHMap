# -*- coding: utf-8 -*-
"""SFTP worker thread of the terminal window (v1.1.3, ROADMAP task 1).

One worker thread per session with a FIFO task queue (list/upload/download):
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
    progress(task_id, done_bytes, total_bytes)
    task_done(task_id, detail)                — detail: final path (file/directory)
    task_error(task_id, kind, message)        — task error; the QUEUE does NOT die
    task_cancelled(task_id, kind)             — cancellation (not an error)

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


class _SftpCancelled(Exception):
    """Internal: cancel/stop was requested during a transfer (not an error)."""


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
    task_error = Signal(int, str, str)       # task_id, kind, message
    task_cancelled = Signal(int, str)        # task_id, kind

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
