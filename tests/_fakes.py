# -*- coding: utf-8 -*-
"""The common test stubs of SSHMap (the suite optimization, phase 2).

Here live the fakes that were previously duplicated in several test files.
Each test file — a separate process (the run_all.py convention), so the shared
classes are safely configured by class attributes: before the scenario their own
interception list is assigned (CaptureMenu.captured / FakeTermWin.spawned /
FakeWidgetThread.sent) — no cross-talk between the files.

The pattern of the SSH-fake wiring (the same seam as before):
    from _fakes import FakeSSHThread as _FakeThread
    ST.SSHTerminalThread = _FakeThread
"""
import posixpath
import threading
import time

from PySide6.QtCore import QThread, Signal as QtSignal
from PySide6.QtWidgets import QMenu, QMessageBox


# ════════════════════════════════════════════════════════════
# QMessageBox.question (v1.4.1 suite cleanup): offscreen there are no modals
# ════════════════════════════════════════════════════════════

class QuestionStub:
    """A `QMessageBox.question` replacement: records every call and answers it.

    Twelve test files used to declare their own `_fake_question()` plus an
    `_orig_question = …` save/restore pair — and the variants disagreed on WHAT
    they recorded (the title alone, a `("question", title, text)` tuple) and on
    WHERE the answer came from (a constant, a one-element list flipped between
    the phases, a queue of answers). All three are arguments here:

        stub = QuestionStub(QMessageBox.StandardButton.Cancel,
                            record=lambda title, text: asked.append(title)).install(ST)
        ...
        stub.answer = QMessageBox.StandardButton.Close   # the next phase answers differently
        ...
        stub.restore()                                   # or: `with stub:` around the block

    `replies` is a QUEUE consumed before `answer` (the "first Yes, then No" case);
    `calls` always keeps `[(title, text), …]` for an assertion that does not want a
    journal of its own. `install()` patches `QMessageBox.question` of the given
    module (or of the real class when called without one — the module attribute IS
    the class, so both spellings patch the same object).
    """

    def __init__(self, answer=None, replies=None, record=None):
        self.answer = QMessageBox.Yes if answer is None else answer
        # the caller's LIST is kept by reference (not copied): a test that appends an answer
        # AFTER the stub was installed must be seen — that is how the queue idiom works.
        self.replies = replies if replies is not None else []
        self.record = record
        self.calls = []
        self._target = None
        self._original = None

    def __call__(self, parent=None, title="", text="", *args, **kwargs):
        title, text = str(title), str(text)
        self.calls.append((title, text))
        if self.record is not None:
            self.record(title, text)
        if self.replies:
            return self.replies.pop(0)
        return self.answer

    def install(self, module=None):
        """Patch `question` on `module.QMessageBox` (default: the real Qt class)."""
        target = QMessageBox if module is None else module.QMessageBox
        self._target = target
        self._original = target.question
        target.question = self
        return self

    def restore(self):
        """Put the original `question` back (idempotent — a second call is a no-op)."""
        if self._target is not None:
            self._target.question = self._original
        self._target = self._original = None

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.restore()


# ════════════════════════════════════════════════════════════
# SSH: a channel + a thread (the same API as SSHTerminalThread)
# ════════════════════════════════════════════════════════════

class FakeSSHChannel:
    """The channel stub. record — the accumulation mode of send():
    "list" — all the bytes (a list), "last" — only the last one, None — does not accumulate.
    resizes (v1.3.3.5) — the (width, height) pairs of every resize_pty() call: the
    terminal-split test counts the debounced PTY resizes of a pane through them.
    """

    def __init__(self, record="list"):
        self.closed = False
        self.sent = [] if record == "list" else None
        self.resizes = []
        self._record = record

    def send(self, data):
        if self._record == "list":
            self.sent.append(data)
        elif self._record == "last":
            self.sent = data

    def resize_pty(self, width=None, height=None):
        self.resizes.append((width, height))

    def close(self):
        self.closed = True

    def is_closed(self):
        return self.closed


class FakeSSHThread(QThread):
    """An idle thread: run() — pass (no real SSH needed).

    RECORD — the channel recording mode by default: "list" | "last" | None (no channel).
    stop_calls counts the stop() calls (part of the gate-scenario specification).
    """
    RECORD = "list"

    output_signal = QtSignal(bytes)
    error_signal = QtSignal(str)
    status_signal = QtSignal(str)
    closed_signal = QtSignal()
    connected_signal = QtSignal()

    def __init__(self, host, user, port, password="", key_path="", record=None):
        super().__init__()
        if record is None:
            record = self.RECORD
        self.host, self.user, self.port = host, user, port
        self.password, self.key_path = password, key_path
        self.client = None
        self.channel = FakeSSHChannel(record) if record is not None else None
        self.running = True
        self.stop_calls = 0

    def run(self):
        pass

    def stop(self):
        self.stop_calls += 1
        self.running = False

    def send_data(self, data_bytes):
        if not data_bytes:
            return
        if self.channel and not self.channel.closed:
            self.channel.send(data_bytes)


class BlockingFakeSSHThread(FakeSSHThread):
    """Simulation of a paramiko connection: run() blocks until release() — a
    "live" session for the ask gate (stop() does not interrupt, like a real connect)."""

    def __init__(self, host, user, port, password="", key_path=""):
        super().__init__(host, user, port, password, key_path)
        self.channel = None
        self._release = threading.Event()

    def run(self):
        self._release.wait(30)   # "connection" — stop() does not interrupt it (like paramiko)
        self.running = False
        try:
            self.closed_signal.emit()
        except RuntimeError:
            pass  # the page is already destroyed — a late emit without receivers is safe

    def release(self):
        self._release.set()


# ════════════════════════════════════════════════════════════
# The QMenu interception (offscreen: exec is not blocking)
# ════════════════════════════════════════════════════════════

class CaptureMenu(QMenu):
    """A QMenu that intercepts exec/exec_: the menu lands in the class list captured.

    Before the scenario:  CaptureMenu.captured = <your list>
    (each test file — a separate process, no mutual interference).
    """
    captured = []

    def exec(self, *a, **k):      # Qt6
        self.captured.append(self)
        return 0

    def exec_(self, *a, **k):     # the legacy name
        self.captured.append(self)
        return 0


# ════════════════════════════════════════════════════════════
# The fake SFTP: an in-memory FS + a client like paramiko SFTPClient
# ════════════════════════════════════════════════════════════

def _norm(path):
    p = path or "/"
    if len(p) > 1 and p.endswith("/"):
        p = p.rstrip("/")
    return p or "/"


class FakeSftpAttr:
    """The same surface as the paramiko SFTPAttributes (filename/st_mode/size/mtime)."""

    def __init__(self, filename, is_dir, size, mtime):
        self.filename = filename
        self.st_mode = 0o40755 if is_dir else 0o100644
        self.st_size = size
        self.st_mtime = mtime


class FakeSftpFS:
    """An in-memory remote FS: dirs (a set of paths) + files (a dict path→bytes).

    deny_write — the file paths where open("wb") raises PermissionError ("no permission").
    deny_dirs (v1.3.3.2) — the DIRECTORIES that refuse new files/directories (a
    read-only directory: with the atomic upload of v1.3.3.2 the worker opens
    `<target>.part`, so a per-FILE denial would no longer model "no write permission").
    remove_dir() — simulates removing the directory ON THE SERVER between the listing and
    the drop (a real-world race: the directory lives in the tree but vanishes on the server).
    """

    def __init__(self, deny_write=frozenset(), deny_dirs=frozenset()):
        self.dirs = {"/"}
        self.files = {}
        self.mtimes = {}
        self.deny_write = set(deny_write)
        self.deny_dirs = set(deny_dirs)

    def add_dir(self, path):
        self.dirs.add(_norm(path))

    def remove_dir(self, path):
        self.dirs.discard(_norm(path))

    def add_file(self, path, data, mtime=1700000000):
        path = _norm(path)
        parent = posixpath.dirname(path)
        if parent not in self.dirs:
            raise ValueError(f"no parent directory {parent}")
        self.files[path] = bytes(data)
        self.mtimes[path] = mtime

    def exists(self, path):
        """A file OR a directory at this path (v1.3.3.2: the rename/mkdir checks)."""
        path = _norm(path)
        return path in self.files or path in self.dirs


class FakeSftpFile:
    """The file of the fake FS; the chunk_delay imitates the network delay per the chunk."""

    def __init__(self, fs, path, mode, chunk_delay=0.0):
        self._fs = fs
        self._path = _norm(path)
        self._pos = 0
        self._delay = chunk_delay
        if "w" in mode or "a" in mode:
            # The paramiko semantics: open("wb") does NOT create the parent directories.
            parent = posixpath.dirname(self._path)
            if parent not in fs.dirs:
                raise IOError("No such file")
            if self._path in fs.deny_write or parent in fs.deny_dirs:
                raise PermissionError("Permission denied")
            if self._path not in fs.files:
                fs.files[self._path] = bytearray()
        else:
            if self._path not in fs.files:
                raise IOError("No such file")

    def read(self, n=-1):
        if self._delay:
            time.sleep(self._delay)
        buf = self._fs.files[self._path]
        end = len(buf) if n < 0 else min(len(buf), self._pos + n)
        data = bytes(buf[self._pos:end])
        self._pos = end
        return data

    def write(self, data):
        if self._delay:
            time.sleep(self._delay)
        buf = self._fs.files.setdefault(self._path, bytearray())
        buf.extend(data)

    def close(self):
        pass


class FakeSftpClient:
    """The fake paramiko SFTPClient (listdir_attr/open/close/get_channel).

    v1.3.3.2 — the file operations of the SFTP tab and the atomic transfer commit:
    mkdir/rmdir/remove/rename/posix_rename. `rename` mimics OpenSSH's sftp-server
    (a v3 rename REFUSES an existing target), `posix_rename` is the
    posix-rename@openssh.com extension (it overwrites — the atomic upload commit).
    posix_rename_ok=False simulates a server WITHOUT the extension, which makes the
    worker take its remove+rename fallback.
    """

    def __init__(self, fs, chunk_delay=0.0):
        self._fs = fs
        self._chunk_delay = chunk_delay
        self._closed = False
        self.posix_rename_ok = True

    def _pause(self):
        if self._chunk_delay:
            time.sleep(self._chunk_delay)

    def listdir_attr(self, path):
        if self._chunk_delay:
            time.sleep(self._chunk_delay)
        path = _norm(path)
        if path not in self._fs.dirs:
            raise IOError("No such file")
        out = []
        for d in sorted(self._fs.dirs):
            if d != "/" and posixpath.dirname(d) == path:
                out.append(FakeSftpAttr(posixpath.basename(d), True, 0,
                                        self._fs.mtimes.get(d, 0)))
        for f in sorted(self._fs.files):
            if posixpath.dirname(f) == path:
                out.append(FakeSftpAttr(posixpath.basename(f), False,
                                        len(self._fs.files[f]),
                                        self._fs.mtimes.get(f, 0)))
        return out

    def open(self, path, mode="r"):
        if self._chunk_delay:
            time.sleep(self._chunk_delay)
        return FakeSftpFile(self._fs, path, mode, self._chunk_delay)

    # ── v1.3.3.2: the file operations (+ the upload commit) ──────────────

    def mkdir(self, path, mode=0o777):
        self._pause()
        path = _norm(path)
        parent = posixpath.dirname(path)
        if parent not in self._fs.dirs:
            raise IOError("No such file")
        if parent in self._fs.deny_dirs:
            raise PermissionError("Permission denied")
        if self._fs.exists(path):
            raise IOError("Failure")
        self._fs.dirs.add(path)
        self._fs.mtimes[path] = int(time.time())

    def rmdir(self, path):
        self._pause()
        path = _norm(path)
        if path not in self._fs.dirs:
            raise IOError("No such file")
        if path in self._fs.deny_dirs:
            raise PermissionError("Permission denied")
        children = [p for p in list(self._fs.dirs) + list(self._fs.files)
                    if p != path and posixpath.dirname(p) == path]
        if children:
            raise IOError("Directory not empty")
        self._fs.dirs.discard(path)
        self._fs.mtimes.pop(path, None)

    def remove(self, path):
        self._pause()
        path = _norm(path)
        if path in self._fs.files:
            del self._fs.files[path]
            self._fs.mtimes.pop(path, None)
            return
        if path in self._fs.dirs:
            raise IOError("Failure")   # a directory needs rmdir (paramiko's remove)
        raise IOError("No such file")

    def rename(self, oldpath, newpath):
        """The SFTP v3 rename — like OpenSSH's sftp-server it refuses an existing target."""
        self._pause()
        if self._fs.exists(newpath):
            raise IOError("Failure")
        self._move(oldpath, newpath)

    def posix_rename(self, oldpath, newpath):
        """posix-rename@openssh.com — the atomic overwrite (the upload commit)."""
        self._pause()
        if not self.posix_rename_ok:
            raise IOError("Operation unsupported")
        self._move(oldpath, newpath)

    def _move(self, oldpath, newpath):
        """Move a file, or a directory WITH its subtree (the target is overwritten)."""
        fs = self._fs
        old = _norm(oldpath)
        new = _norm(newpath)
        if old in fs.files:
            if new in fs.files:
                del fs.files[new]
            fs.files[new] = fs.files.pop(old)
            if old in fs.mtimes:
                fs.mtimes[new] = fs.mtimes.pop(old)
            return
        if old in fs.dirs:
            for d in sorted(p for p in list(fs.dirs)
                            if p == old or p.startswith(old + "/")):
                fs.dirs.discard(d)
                fs.dirs.add(new + d[len(old):])
            for f in sorted(p for p in list(fs.files) if p.startswith(old + "/")):
                fs.files[new + f[len(old):]] = fs.files.pop(f)
                if f in fs.mtimes:
                    fs.mtimes[new + f[len(old):]] = fs.mtimes.pop(f)
            if old in fs.mtimes:
                fs.mtimes[new] = fs.mtimes.pop(old)
            return
        raise IOError("No such file")

    def get_channel(self):
        return self  # "channel" = the client itself (the closed attribute for the worker check)

    @property
    def closed(self):
        return self._closed

    def close(self):
        self._closed = True


class EventLog:
    """The journal of the worker's signals (queued delivery in the GUI thread via wait_until)."""

    def __init__(self):
        self.events = []
        self.lock = threading.Lock()

    def add(self, *ev):
        with self.lock:
            self.events.append(ev)

    def of_kind(self, kind, task_id=None):
        with self.lock:
            return [e for e in self.events if e[0] == kind
                    and (task_id is None or len(e) > 1 and e[1] == task_id)]


def wire_worker(worker, log):
    worker.list_ready.connect(lambda tid, d, e: log.add("list", tid, d, e))
    worker.task_started.connect(lambda tid, k, l: log.add("started", tid, k, l))
    worker.progress.connect(lambda tid, dn, tot: log.add("progress", tid, dn, tot))
    worker.task_done.connect(lambda tid, det: log.add("done", tid, det))
    worker.task_error.connect(lambda tid, k, m: log.add("error", tid, k, m))
    worker.task_cancelled.connect(lambda tid, k: log.add("cancelled", tid, k))
    # v1.3.1: the viewer's read answer (task_id, remote_path, bytes)
    worker.read_ready.connect(lambda tid, p, data: log.add("read", tid, p, data))


# ════════════════════════════════════════════════════════════
# The paramiko client fakes for the terminal window (get_transport/open_sftp)
# ════════════════════════════════════════════════════════════

class FakeTransport:
    def __init__(self, active=True):
        self._active = active

    def is_active(self):
        return self._active


class FakeSSHClient:
    """The paramiko SSHClient surface for the terminal window: get_transport/open_sftp.
    open_sftp() with sftp=None raises Exception ("SFTP subsystem disabled")."""

    def __init__(self, sftp_client):
        self._sftp = sftp_client
        self._tr = FakeTransport(True)

    def get_transport(self):
        return self._tr

    def open_sftp(self):
        if self._sftp is None:
            raise Exception("SFTP subsystem disabled")
        return self._sftp

    def close(self):
        pass


# ════════════════════════════════════════════════════════════
# Mini stubs of the widgets (the SSH dialogs) and the terminal window
# ════════════════════════════════════════════════════════════

class FakeLineEdit:
    """A mini stub of QLineEdit."""
    def __init__(self, v): self._v = v
    def text(self): return self._v
    def setText(self, v): self._v = v


class FakeSpinBox:
    """A mini stub of QSpinBox."""
    def __init__(self, v): self._v = v
    def value(self): return self._v


class DummySignal:
    """A signal stub: connect() — a no-op."""
    def connect(self, *a, **k): pass


class FakeTermWin:
    """The fake terminal window (SSHTerminalWindow): it fixes the arguments of the constructor.
    The list of the created windows is set by the class attribute spawned before the scenario."""
    spawned = []

    def __init__(self, server_data, parent=None, password=None, initial_command=""):
        self.server_data = server_data
        self.password = password
        self.initial_command = initial_command
        self.destroyed = DummySignal()
        self.spawned.append(self)

    def show(self): pass


# ════════════════════════════════════════════════════════════
# A thread stub for the TerminalWidget (the widget level, not a QThread)
# ════════════════════════════════════════════════════════════

class FakeWidgetThread:
    """send_data → the class list sent (before the scenario: FakeWidgetThread.sent = [])."""
    sent = []

    def send_data(self, b):
        self.sent.append(b)

    def stop(self):
        pass
