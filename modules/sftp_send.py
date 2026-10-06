# -*- coding: utf-8 -*-
"""The cross-session relay behind `Send to ▸ <session>` (v1.7.3) — the orchestrator and its dialog.

ONE conversation over the SHIPPED worker kinds: the SAME `(host, ssh_port, user)` is a server-side
`queue_copy()` on the source worker, a DIFFERENT end is a RELAY through this machine — a download
into ONE spool file under the OS temp and an upload out of it, each leg atomic and cancellable.
`SendFileDialog` names the file, its folder, the target session and the identity the server-side
path runs as; the conflict question gains BOTH sides' size and date. There is deliberately no
server-to-server path. Rules — `AGENTS.md`
§4.3/§4.24; mechanism — `DOCUMENTATION.md` §66; the spool sentence — `README.md`, Security.
"""
import os
import posixpath
import stat
import tempfile
import time

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QVBoxLayout, QWidget)

try:
    from i18n import t as _t
except Exception:  # noqa: BLE001 — import outside the project tree (flat run)
    def _t(key, **kwargs):  # type: ignore
        return key

try:
    from .sftp_worker import PART_SUFFIX
except ImportError:  # flat launch from the project root
    from sftp_worker import PART_SUFFIX

#: The ceiling of ONE send between sessions — the ask's own number, checked against the row's
#: size BEFORE leg 1 (a config key can wait; `terminal_max_open` is the precedent).
MAX_SEND_BYTES = 100 * 1024 * 1024

#: The spool: ONE file under the OS temp, the tightest mode the platform offers, created under a
#: name nobody else could have claimed (`mkstemp`) and recognized by its prefix, so the startup
#: sweep can take the leftovers of a CRASHED run (a plaintext copy must not outlive the app).
SPOOL_PREFIX = "sshmap-send-"
SPOOL_FILE_MODE = 0o600

#: The age a spool may reach before the startup sweep takes it. An AGE rule is the portable one:
#: `os.kill(pid, 0)` is not portable on Windows and a pid is recycled, while a LIVE sibling
#: instance keeps its spools young — a relay in flight is never cut in half by another instance.
SPOOL_MAX_AGE_SEC = 6 * 60 * 60

#: The TWO declared paths of a send — reported in the result and asserted by the topical file.
SEND_STRATEGY_SERVER = "server_side"
SEND_STRATEGY_RELAY = "relay"

#: The leg a task belongs to (the relay's own bookkeeping — the worker knows only its KIND).
SEND_LEG_COPY = "copy"
SEND_LEG_DOWNLOAD = "download"
SEND_LEG_UPLOAD = "upload"

#: The dialog's "accepted" answer, named once so a test double can return it.
DIALOG_ACCEPTED = QDialog.DialogCode.Accepted


def same_host(source, target) -> bool:
    """Do the two endpoints name the SAME SSH end AND the same identity? (the server-side path).

    Two `SFTPClient`s cannot talk to each other, so a DIFFERENT host is always a relay through this
    machine — while the same host reached through two sessions can copy SERVER-SIDE. The comparison
    is `(host, ssh_port, user)`: the server-side copy executes on the SOURCE session's client, i.e.
    as the source session's user, so two sessions of one host with DIFFERENT users must take the
    relay (which obeys the target's own rights). An unknown host or user is never "the same".
    """
    if source is None or target is None:
        return False
    host = str(getattr(source, "host", "") or "").strip().lower()
    other = str(getattr(target, "host", "") or "").strip().lower()
    if not host or host != other or _port(source) != _port(target):
        return False
    user = str(getattr(source, "user", "") or "").strip()
    return bool(user) and user == str(getattr(target, "user", "") or "").strip()


def _port(endpoint) -> int:
    """The endpoint's SSH port (22 — the application's own default)."""
    try:
        return int(getattr(endpoint, "port", 22) or 22)
    except (TypeError, ValueError):
        return 22


def size_allowed(size, limit: int = MAX_SEND_BYTES) -> bool:
    """Is this many bytes inside the declared ceiling of ONE send?"""
    try:
        return 0 <= int(size or 0) <= int(limit)
    except (TypeError, ValueError):
        return False


class SendEndpoint:
    """ONE side of a send: the session's identity, transport, directory and visible listing.

    A plain object (no Qt): the provider that builds it lives in `ui/main_window_ssh.py`, the
    comparison it feeds is `same_host()`, and a test hands in whatever it likes. `user` is part of
    the identity the comparison reads — the server-side copy runs as the SOURCE session's user.
    """

    __slots__ = ("key", "label", "host", "port", "user", "worker", "directory", "folders", "facts",
                 "refresh")

    def __init__(self, key="", label="", host="", port=None, user="", worker=None, directory="/",
                 folders=(), facts=None, refresh=None):
        self.key = str(key or "")
        self.label = str(label or "")
        self.host = str(host or "")
        self.port = port
        self.user = str(user or "")
        self.worker = worker
        self.directory = str(directory or "/")
        self.folders = tuple(folders or ())
        self.facts = dict(facts or {})
        self.refresh = refresh


def pane_listing_facts(pane) -> tuple:
    """`({name: (is_dir, size, mtime)}, [folder paths])` of a pane's OWN listing — no network.

    The target pane's tree IS the server's answer for its current directory, so the folder picker
    and the conflict check need no listing of their own; the roles are read defensively (a pane
    built before its tree exists answers empty rather than raising).
    """
    facts, folders = {}, []
    try:
        count = int(pane.tree.topLevelItemCount())
    except (AttributeError, RuntimeError, TypeError):
        return facts, folders
    path_role = getattr(pane, "PATH_ROLE", None)
    isdir_role = getattr(pane, "ISDIR_ROLE", None)
    size_role = getattr(pane, "SIZE_ROLE", None)
    mtime_role = getattr(pane, "MTIME_ROLE", None)
    if None in (path_role, isdir_role, size_role, mtime_role):
        return facts, folders
    up_item = getattr(pane, "_up_item", None)
    for index in range(count):
        try:
            item = pane.tree.topLevelItem(index)
        except RuntimeError:
            break
        if item is None or item is up_item:
            continue
        name = item.text(0)
        is_dir = bool(item.data(0, isdir_role))
        facts[name] = (is_dir, int(item.data(0, size_role) or 0), int(item.data(0, mtime_role) or 0))
        if is_dir:
            folders.append(str(item.data(0, path_role) or ""))
    return facts, folders


def endpoint_from_tab(tab, key="", label="", host="", port=None, user="", worker=None) -> SendEndpoint:
    """The endpoint of a LIVE Files container: its ACTIVE pane's directory, folders and rows."""
    pane = getattr(tab, "active_pane", None)
    facts, folders = (pane_listing_facts(pane) if pane is not None else ({}, []))
    return SendEndpoint(key=key, label=label, host=host, port=port, user=user, worker=worker,
                        directory=str(getattr(pane, "current_dir", "/") or "/"),
                        folders=folders, facts=facts,
                        refresh=getattr(tab, "relist_dir", None))


def facts_from_entries(entries) -> dict:
    """A worker listing → the same `{name: (is_dir, size, mtime)}` map the tree gives."""
    facts = {}
    for entry in entries or ():
        try:
            name = str(entry["name"])
        except (KeyError, TypeError):
            continue
        facts[name] = (bool(entry.get("is_dir")), int(entry.get("size") or 0),
                       int(entry.get("mtime") or 0))
    return facts


# ── The spool ────────────────────────────────────────────────────────────────

def spool_dir() -> str:
    """The OS temp directory — the ONE place a relay may leave a copy of a remote file."""
    return tempfile.gettempdir()


def _spool_base(name: str) -> str:
    """The file name of ONE send, platform-safe and recognizable (`payload.bin`)."""
    return posixpath.basename(str(name or "").replace("\\", "/")) or "file"


def spool_path(name: str = "", token=None) -> str:
    """The LOGICAL spool name of ONE send (the shipped spelling; `create_spool()` claims a real one)."""
    stamp = int(token) if token is not None else int(time.time() * 1000)
    return os.path.join(spool_dir(), f"{SPOOL_PREFIX}{os.getpid()}-{stamp}-{_spool_base(name)}")


def create_spool(name: str = "", token=None) -> str:
    """Claim a UNIQUE spool file with `mkstemp`; answers "" when the folder refused it.

    The name nobody else could have claimed is what closes the planted-name case, and `mkstemp`
    creates the file 0600 in one exclusive step. The prefix keeps it sweepable and the basename
    keeps it recognizable; the fd is closed at once, because the download leg re-opens the path.
    """
    stamp = int(token) if token is not None else int(time.time() * 1000)
    try:
        handle, path = tempfile.mkstemp(prefix=f"{SPOOL_PREFIX}{os.getpid()}-{stamp}-",
                                        suffix=f"-{_spool_base(name)}", dir=spool_dir())
    except OSError:
        return ""
    os.close(handle)
    try:
        os.chmod(path, SPOOL_FILE_MODE)   # the tightest mode the platform offers
    except OSError:
        pass
    return path


def _is_our_empty_twin(path: str) -> bool:
    """Is this path the UNTOUCHED provisional file of an earlier attempt of OURS? (never a plant).

    An EXISTING name is verified, never assumed: a symlink (a plain link is not a regular file),
    a hard link to somebody's file (`st_nlink`), a file with content, a foreign owner and a stale
    file are all refusals.
    """
    try:
        info = os.lstat(path)
    except OSError:
        return False
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != 0:
        return False
    getuid = getattr(os, "getuid", None)
    if getuid is not None:
        try:
            if info.st_uid != getuid():
                return False
        except OSError:
            return False
    return (time.time() - info.st_mtime) <= SPOOL_MAX_AGE_SEC


def prepare_spool(path: str) -> bool:
    """Claim the spool's provisional twin BEFORE the first leg; False — this send cannot start.

    The probe is what the relay's "spool" refusal is made of (the folder takes a file and the name
    is ours). The twin is created EXCLUSIVELY and an existing one is VERIFIED (`_is_our_empty_twin`)
    instead of accepted: a name somebody planted answers False. The MODE of the committed spool
    comes from the WRITER — the download leg creates its own provisional file with `SPOOL_FILE_MODE`
    (`queue_download(part_mode=…)`), because `os.replace()` publishes that file's inode and the
    destination's mode does not survive it.
    """
    if not path:
        return False
    twin = path + PART_SUFFIX
    try:
        fd = os.open(twin, os.O_CREAT | os.O_EXCL | os.O_WRONLY, SPOOL_FILE_MODE)
    except FileExistsError:
        return _is_our_empty_twin(twin)
    except OSError:
        return False
    os.close(fd)
    return True


def drop_spool(path: str) -> int:
    """Delete a spool file AND its provisional twin; returns how many files went. Never raises.

    The WORKER's own provisional name (`<spool>.<pid>-<task>.part`) is deliberately not named here:
    it never outlives its task (the commit renames it, the failure and cancel paths remove it), and
    a crash's leftover is the startup sweep's, which matches by PREFIX.
    """
    removed = 0
    for candidate in (path, f"{path}{PART_SUFFIX}" if path else ""):
        if not candidate:
            continue
        try:
            os.remove(candidate)
            removed += 1
        except OSError:
            continue   # never created / already gone — nothing to clean
    return removed


def sweep_spools(directory: str = "", max_age_sec=SPOOL_MAX_AGE_SEC) -> int:
    """Delete the spools of a CRASHED run — only the ones past the declared age. Never raises.

    The age rule is the owner rule: a live sibling instance keeps its spools (they are young, and
    its relay may be mid-flight), while a crashed run's leftovers go at the next startup.
    """
    folder = directory or spool_dir()
    removed = 0
    try:
        names = os.listdir(folder)
    except OSError:
        return 0
    now = time.time()
    for name in names:
        if not name.startswith(SPOOL_PREFIX):
            continue
        candidate = os.path.join(folder, name)
        try:
            if (now - os.lstat(candidate).st_mtime) <= float(max_age_sec):
                continue   # young enough to belong to a live instance (or to this one)
        except (OSError, TypeError, ValueError):
            continue
        removed += drop_spool(candidate)
    return removed


# ── The rendering helpers (the shipped size/date pair, imported late) ────────

def _formatters():
    """The SHIPPED `format_size()` / `format_mtime()` — imported late, `sftp_tab` imports THIS."""
    try:
        from .sftp_tab import format_mtime, format_size
    except ImportError:  # flat launch from the project root
        from sftp_tab import format_mtime, format_size
    return format_size, format_mtime


def _size_text(value) -> str:
    return _formatters()[0](value)


def _date_text(value) -> str:
    return _formatters()[1](value)


def conflict_facts(entry, existing) -> str:
    """The BOTH-sides facts line of the overwrite question (ONE key, ONE `\\n`)."""
    is_dir, size, mtime = existing or (False, 0, 0)
    return _t("sftp.conflict.facts",
              source_size=_size_text(entry.get("size")), source_date=_date_text(entry.get("mtime")),
              target_size=_size_text(size), target_date=_date_text(mtime))


def ask_overwrite(parent, name: str, target: str, facts: str = "") -> bool:
    """The overwrite question with both sides' facts — the shipped dialog, one more line."""
    try:
        from .sftp_tab import ask_conflict
    except ImportError:  # flat launch from the project root
        from sftp_tab import ask_conflict
    action, _apply_all = ask_conflict(parent, name, target, 0, facts=facts)
    return action == "overwrite"


# ── The transfer of ONE file: the two legs, composed ────────────────────────

class SendRelay(QObject):
    """The bytes of ONE send: `queue_download` + `queue_upload`, or the server-side `queue_copy`.

    Every answer is matched by its TASK ID, so a transfer the user started in a pane is never
    counted into the send; the two legs are composed into ONE progress signal (`done`/`total` over
    BOTH). The spool is dropped on success, failure and cancel alike, and the WORKER keeps its own
    atomicity (`<target>.part` + one commit).
    """

    progress = Signal(int, int)   # done_bytes, total_bytes — the TWO legs composed
    finished = Signal(dict)       # {ok, cancelled, error, name, dir, strategy, bytes}

    def __init__(self, source, target, entry, parent=None):
        super().__init__(parent)
        self.source = source
        self.target = target
        self.entry = dict(entry or {})
        self._tasks = {}     # task_id → the leg it belongs to
        self._bound = []     # the (worker, slot) pairs this relay connected
        self._spool = ""
        self._name = str(self.entry.get("name") or "")
        self._dir = "/"
        self._strategy = ""
        self._done = False

    @property
    def strategy(self) -> str:
        """`server_side` | `relay` — which of the two declared paths this send takes."""
        return self._strategy

    @property
    def spool(self) -> str:
        """The local spool file of a RELAY send ("" — the server-side path needs none)."""
        return self._spool

    def start(self, target_dir: str, name: str = "") -> bool:
        """Queue the FIRST leg; False — there is nothing to transfer through. Never raises."""
        worker = self.source.worker
        source_path = str(self.entry.get("path") or "")
        self._dir = str(target_dir or "/") or "/"
        self._name = str(name or self.entry.get("name") or "")
        if worker is None or not source_path or not self._name:
            self._finish(False, error="no transport")
            return False
        if same_host(self.source, self.target):
            # ONE leg: the server copies the file to itself (the `copy-data` fast path included).
            self._strategy = SEND_STRATEGY_SERVER
            self._bind(worker)
            return self._register(worker.queue_copy(source_path, self._dir, self._name),
                                  SEND_LEG_COPY)
        # TWO legs through this machine: the spool is the only path between the two transports.
        self._strategy = SEND_STRATEGY_RELAY
        spool = create_spool(self._name)
        if not spool or not prepare_spool(spool):
            drop_spool(spool)   # a refused send leaves nothing of ours in the temp folder
            self._finish(False, error="spool")
            return False
        self._spool = spool
        self._bind(worker)
        self._bind(self.target.worker)
        task = worker.queue_download(source_path, os.path.dirname(self._spool),
                                     total_size=int(self.entry.get("size") or 0),
                                     local_name=os.path.basename(self._spool),
                                     part_mode=SPOOL_FILE_MODE)
        return self._register(task, SEND_LEG_DOWNLOAD)

    def cancel(self):
        """Cancel the send through the SHIPPED queue (the worker's ONE cancel flag).

        The flag belongs to the WORKER, so a cancel covers whatever else the two queues hold — the
        shipped contract of the pane's "Cancel" button, which is why the relay leaves the flag to
        the worker instead of inventing a second stop mechanism.
        """
        for worker in (self.source.worker, self.target.worker):
            if worker is None:
                continue
            try:
                worker.cancel()
            except Exception:  # noqa: BLE001 — a dead transport is already "cancelled"
                continue

    # ── the wiring ──

    def _bind(self, worker):
        """Connect THIS relay to one worker once (task ids keep strangers out)."""
        if worker is None or any(w is worker for w, _name, _slot in self._bound):
            return
        for name, slot in (("progress", self._on_progress), ("task_done", self._on_task_done),
                           ("task_error", self._on_task_error),
                           ("task_cancelled", self._on_task_cancelled),
                           ("finished", self._on_worker_finished)):
            signal = getattr(worker, name, None)
            if signal is None:
                continue
            try:
                signal.connect(slot)
                self._bound.append((worker, name, slot))
            except (RuntimeError, TypeError):
                continue   # a foreign worker object in a test — the relay still runs

    def _unbind(self):
        """Drop every connection of this relay (a send owns its slots for its lifetime only)."""
        for worker, name, slot in list(self._bound):
            signal = getattr(worker, name, None)
            if signal is None:
                continue
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                continue   # never connected / the worker is already gone
        self._bound = []

    def _register(self, task_id, leg: str) -> bool:
        """Remember a queued leg; a refused queue (None) is a failed send, never a silent one."""
        if task_id is None:
            self._finish(False, error="queue")
            return False
        self._tasks[int(task_id)] = leg
        return True

    def _finish(self, ok: bool, error: str = "", cancelled: bool = False):
        """Emit the ONE result and drop the spool — idempotent (the legs are asynchronous)."""
        if self._done:
            return
        self._done = True
        drop_spool(self._spool)
        self._unbind()
        self.finished.emit({"ok": bool(ok), "cancelled": bool(cancelled), "error": str(error or ""),
                            "name": self._name, "dir": self._dir, "strategy": self._strategy,
                            "bytes": int(self.entry.get("size") or 0)})

    # ── the answers ──

    def _on_progress(self, task_id: int, done: int, total: int):
        """Compose the two legs onto ONE line: the download is the first half, the upload the rest."""
        leg = self._tasks.get(int(task_id))
        if leg is None:
            return
        span = int(total or 0) or int(self.entry.get("size") or 0)
        if leg == SEND_LEG_DOWNLOAD and self._strategy == SEND_STRATEGY_RELAY:
            self.progress.emit(int(done), max(2 * span, int(done)))
        elif leg == SEND_LEG_UPLOAD:
            self.progress.emit(span + int(done), max(2 * span, span + int(done)))
        else:
            self.progress.emit(int(done), max(span, int(done)))

    def _on_task_done(self, task_id: int, detail: str):
        leg = self._tasks.pop(int(task_id), None)
        if leg is None:
            return
        if leg == SEND_LEG_DOWNLOAD:
            task = self.target.worker.queue_upload(self._spool, self._dir,
                                                   remote_name=self._name) \
                if self.target.worker is not None else None
            if not self._register(task, SEND_LEG_UPLOAD):
                return   # the second leg could not be queued — `_register` reported it
            return
        self._finish(True)

    def _on_task_error(self, task_id: int, kind: str, message: str):
        if self._tasks.pop(int(task_id), None) is None:
            return
        self._finish(False, error=str(message or ""))

    def _on_task_cancelled(self, task_id: int, kind: str):
        if self._tasks.pop(int(task_id), None) is None:
            return
        self._finish(False, cancelled=True)

    def _on_worker_finished(self):
        """The transport died mid-send: the send cannot continue (the spool is still dropped)."""
        if self._tasks:
            self._tasks.clear()
            self._finish(False, error="transport")


# ── The dialog: the file, the target and the folder ─────────────────────────

class SendFileDialog(QDialog):
    """`Send to…`: the file and its folder, the target session and the folder it lands in.

    The folder picker is an EDITABLE combo fed by the TARGET pane's own listing (the caller passes
    it — a menu costs no listing), its default is the source's folder when the server really has it
    (`SendCoordinator` asks), and the note names which of the two declared paths the bytes take.
    The dialog answers ONE question (`chosen_dir()`); the conflict follows it, with both sides'
    facts. A test builds it and reads the widgets — `exec()` never runs offscreen.
    """

    def __init__(self, parent=None, entry=None, target=None, folders=(), default_dir="/",
                 same_host=True, user=""):
        super().__init__(parent)
        self._entry = dict(entry or {})
        name = str(self._entry.get("name") or "?")
        source_path = str(self._entry.get("path") or "")
        self.setWindowTitle(_t("sftp.send.title", name=name))
        layout = QVBoxLayout(self)
        head = QLabel(_t("sftp.send.file_line", name=name, size=_size_text(self._entry.get("size")),
                         dir=posixpath.dirname(source_path) or "/"))
        head.setWordWrap(True)
        layout.addWidget(head)
        target_line = QLabel(_t("sftp.send.target_line",
                                alias=str(getattr(target, "label", "") or getattr(target, "host", "") or "?"),
                                host=str(getattr(target, "host", "") or "?"),
                                dir=str(getattr(target, "directory", "") or "/")))
        target_line.setWordWrap(True)
        layout.addWidget(target_line)
        row = QHBoxLayout()
        row.addWidget(QLabel(_t("sftp.send.folder_prompt")))
        self.folder_combo = QComboBox(self)
        self.folder_combo.setEditable(True)
        for folder in self.folder_choices(folders, default_dir):
            self.folder_combo.addItem(folder)
        self.folder_combo.setCurrentText(str(default_dir or "/") or "/")
        row.addWidget(self.folder_combo, 1)
        layout.addLayout(row)
        note = QLabel(_t("sftp.send.same_host_note") if same_host else _t("sftp.send.relay_note"))
        note.setWordWrap(True)
        layout.addWidget(note)
        # The server-side copy runs as the SOURCE session's user — the ONE sentence that names it.
        self.user_note = None
        if same_host:
            self.user_note = QLabel(_t("sftp.send.same_host_user_note", user=str(user or "?")))
            self.user_note.setWordWrap(True)
            layout.addWidget(self.user_note)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    @staticmethod
    def folder_choices(folders, default_dir) -> list:
        """The default folder first, then the target's own folders — ONE absolute path each."""
        out = []
        for folder in [str(default_dir or "")] + [str(f or "") for f in (folders or ())]:
            if folder.startswith("/") and folder not in out:
                out.append(folder)
        return out or ["/"]

    def chosen_dir(self) -> str:
        """The folder the user picked (the editable combo's text; "/" for an empty field)."""
        try:
            text = str(self.folder_combo.currentText() or "").strip()
        except (RuntimeError, AttributeError):
            text = ""
        return text or "/"


# ── The conversation: the folder, the conflict, then the relay ──────────────

class SendCoordinator(QObject):
    """The `Send to…` conversation of ONE file: resolve the target's folder, ask, then transfer.

    The steps are SEQUENTIAL and each one is a signal away: the source folder is probed on the
    TARGET (an existence question, not a guess), the dialog asks for the destination, the chosen
    folder is listed when it is not the one on the target's screen (so the conflict is the server's
    own answer), and only then do the legs run. A refused or cancelled step emits `finished` with
    the reason and NEVER starts a transfer.
    """

    report = Signal(str)          # ONE translated sentence for the pane's status line
    progress = Signal(int, int)   # re-emitted from the relay (the TWO legs composed)
    finished = Signal(dict)       # the relay's result, or {ok: False, cancelled|skipped|too_big}

    def __init__(self, source, target, entry, parent=None, asker=None):
        super().__init__(parent)
        self.source = source
        self.target = target
        self.entry = dict(entry or {})
        self._parent = parent if isinstance(parent, QWidget) else None
        self._asker = asker if callable(asker) else ask_overwrite
        self._relay = None
        self._dialog = None
        self._probe_task = None
        self._list_task = None
        self._pending_run = None
        self._bound = []
        self._known = dict(getattr(target, "facts", None) or {})
        self._default = str(getattr(target, "directory", "") or "/") or "/"
        self._folders = list(getattr(target, "folders", None) or ())
        self._done = False

    @property
    def dialog(self):
        """The dialog of the LAST question (the test seam — the class is a module attribute)."""
        return self._dialog

    def start(self) -> bool:
        """Ask the TARGET whether the source's folder exists there, then open the dialog."""
        if self._relay is not None:
            return False
        worker = self.target.worker
        source_dir = str(getattr(self.source, "directory", "") or "")
        if worker is not None and source_dir.startswith("/") and source_dir != self._default:
            task = worker.queue_list(source_dir)
            if task is not None and self._attach(worker):
                self._probe_task = int(task)
                return True
        self._open_dialog()
        return True

    def run(self, target_dir: str, name: str = "") -> bool:
        """Resolve the conflict in `target_dir` and start the legs (the seam a test drives)."""
        if self._relay is not None or self._done:
            return False
        target_dir = str(target_dir or "").strip() or "/"
        name = str(name or self.entry.get("name") or "")
        facts = self._known if target_dir == str(getattr(self.target, "directory", "") or "") else None
        if facts is None and self.target.worker is not None:
            task = self.target.worker.queue_list(target_dir)
            if task is not None and self._attach(self.target.worker):
                self._pending_run = (target_dir, name)
                self._list_task = int(task)
                return True
            facts = {}
        self._conflict_and_send(target_dir, name, facts or {})
        return True

    def cancel(self):
        """Cancel the send (the spool goes with it, whichever leg is in flight)."""
        if self._relay is not None:
            self._relay.cancel()

    # ── the steps ──

    def _attach(self, worker) -> bool:
        """Listen to the TARGET's listings and errors once (its answers carry our task ids)."""
        if worker is None:
            return False
        for name, slot in (("list_ready", self._on_list_ready), ("task_error", self._on_task_error)):
            signal = getattr(worker, name, None)
            if signal is None:
                return False
            if any(w is worker and n == name for w, n, _slot in self._bound):
                continue
            try:
                signal.connect(slot)
                self._bound.append((worker, name, slot))
            except (RuntimeError, TypeError):
                return False
        return True

    def _detach(self):
        """Drop the coordinator's slots from the target worker (never the pane's own)."""
        for worker, name, slot in list(self._bound):
            signal = getattr(worker, name, None)
            if signal is None:
                continue
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                continue   # never connected / the worker is already gone
        self._bound = []

    def _open_dialog(self):
        """Ask the ONE question of the send: WHERE the file lands (and say what it is)."""
        dialog = SendFileDialog(self._parent, self.entry, self.target, folders=self._folders,
                                default_dir=self._default,
                                same_host=same_host(self.source, self.target),
                                user=str(getattr(self.source, "user", "") or ""))
        self._dialog = dialog
        accepted = False
        try:
            accepted = int(dialog.exec()) == int(DIALOG_ACCEPTED)
        except Exception:  # noqa: BLE001 — a dialog must never break a send
            accepted = False
        chosen = dialog.chosen_dir() if accepted else ""
        if not accepted or not chosen:
            self._finish({"ok": False, "cancelled": True})
            return
        self.run(chosen)

    def _conflict_and_send(self, target_dir: str, name: str, facts: dict):
        """The size gate, the overwrite question with BOTH sides' facts, then the relay."""
        size = int(self.entry.get("size") or 0)
        if not size_allowed(size):
            self.report.emit(_t("sftp.send.too_big", name=name, size=_size_text(size),
                                limit=_size_text(MAX_SEND_BYTES)))
            self._finish({"ok": False, "too_big": True})
            return
        existing = (facts or {}).get(name)
        if existing is not None and not bool(existing[0]):
            if not self._asker(self._parent, name, target_dir, conflict_facts(self.entry, existing)):
                self._finish({"ok": False, "skipped": True})
                return
        self._start_relay(target_dir, name)

    def _start_relay(self, target_dir: str, name: str):
        """Hand the file to the relay (the shipped kinds are the whole transfer engine)."""
        relay = SendRelay(self.source, self.target, {**self.entry, "name": name}, parent=self)
        relay.progress.connect(self.progress)
        relay.finished.connect(self._on_relay_finished)
        self._relay = relay
        if not relay.start(target_dir, name):
            self._relay = None

    def _finish(self, result: dict):
        """Emit the ONE closing answer (a cancelled dialog is quiet, a failure is a sentence)."""
        if self._done:
            return
        self._done = True
        self._detach()
        self._relay = None
        self.finished.emit(dict(result))

    def _on_relay_finished(self, result: dict):
        alias = str(getattr(self.target, "label", "") or getattr(self.target, "host", "") or "?")
        name = str(self.entry.get("name") or "")
        if result.get("ok"):
            self.report.emit(_t("sftp.send.done", name=name, alias=alias,
                                dir=str(result.get("dir") or "")))
        elif result.get("cancelled"):
            self.report.emit(_t("sftp.transfer_cancelled"))
        else:
            self.report.emit(_t("sftp.send.failed", name=name, alias=alias,
                                error=str(result.get("error") or "")))
        self._finish(result)

    def _on_list_ready(self, task_id: int, remote_dir: str, entries: list):
        """The answer to the folder probe OR to the chosen folder's listing."""
        if self._probe_task is not None and int(task_id) == self._probe_task:
            self._probe_task = None
            if str(remote_dir or "") == str(getattr(self.source, "directory", "") or ""):
                self._default = str(remote_dir)     # the folder really exists on the target
            self._open_dialog()
            return
        if self._list_task is not None and int(task_id) == self._list_task:
            self._list_task = None
            pending = self._pending_run or ("/", "")
            self._pending_run = None
            self._conflict_and_send(str(pending[0]), str(pending[1]),
                                    facts_from_entries(entries))

    def _on_task_error(self, task_id: int, kind: str, message: str):
        """A failed listing: the folder probe falls back, the chosen folder is reported."""
        if self._probe_task is not None and int(task_id) == self._probe_task:
            self._probe_task = None
            self._open_dialog()      # the source's folder is not there — the target's own is used
            return
        if self._list_task is not None and int(task_id) == self._list_task:
            self._list_task = None
            pending = self._pending_run or ("/", "")
            self._pending_run = None
            self.report.emit(_t("sftp.op.error", error=str(message or "")))
            self._conflict_and_send(str(pending[0]), str(pending[1]), {})
