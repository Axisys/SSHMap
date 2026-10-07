# -*- coding: utf-8 -*-
"""v1.7.4 — the LOCAL pane, the closing release: the CLAUSE AUDIT of the frozen contract
(LOCAL_PANE.md) against the shipped code.

The rc series IMPLEMENTED the frozen contract; this release VERIFIES it — a GATE, not a paragraph:
every owner, name, code, refusal and rule is read off the SHIPPED objects, so a clause that quietly
stops being true fails in the suite. ALL checks are offscreen: the fake SFTP surface and a real OS
tree inside the isolated HOME. §1 the provider seam; §2 the dialect; §3 the surface and its codes;
§4 the switch; §5 the dispatch; §6 the recursion; §7 the drag & drop; §8 the boundary; §9 the state."""
import os
import shutil
import sys

from _common import (bootstrap, check, finish, wait_until, wait_for, clear_cfg, write_cfg,
                     load_i18n_langs, check_i18n_parity, check_i18n_format, check_release_state,
                     pane_family_files, pane_family_text, pane_func_body, pane_func_owner,
                     releases_at_least, EXPECTED_APP_VERSION, EXPECTED_I18N_KEYS)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation)

from PySide6.QtCore import QPointF, Qt as _Qt
from PySide6.QtWidgets import QApplication, QWidget

app = QApplication(sys.argv)

import i18n
import modules.local_fs_worker as LFW
import modules.sftp_tab as STAB
import modules.sftp_worker as SW
from modules.sftp_tab import (LOCAL_PATHS, PANE_DRAG_MIME, PANE_SOURCES, POSIX_PATHS, SOURCE_LOCAL,
                              SOURCE_REMOTE, WORKER_SIGNAL_NAMES, SftpTab, dialect_for,
                              pane_payload)
from modules.sftp_worker import (KIND_COPY, KIND_MOVE, MAX_TREE_DEPTH, MAX_TREE_ENTRIES,
                                 PART_SUFFIX, PARTIAL_CODE, TREE_ERROR_TOO_BIG, SftpWorker,
                                 parse_task_payload)
from _fakes import EventLog, FakeSftpClient, FakeSftpFS, wire_worker

TREE = os.path.join(WORK, "contract_tree")

PANE_SRC = pane_family_text(ROOT)
PANE_FILES = pane_family_files(ROOT)
ENGINE_SRC = open(os.path.join(ROOT, "modules", "local_fs_worker.py"), encoding="utf-8").read()
CONTRACT = open(os.path.join(ROOT, "LOCAL_PANE.md"), encoding="utf-8").read()
PANES_CONTRACT = open(os.path.join(ROOT, "SFTP_PANES.md"), encoding="utf-8").read()
LANGS = load_i18n_langs(ROOT)


def fresh_dir(name, *files):
    """A clean directory under WORK, optionally with `(relative path, bytes)` files in it."""
    path = os.path.join(WORK, name)
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path)
    for rel, data in files:
        full = os.path.join(path, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(data)
    return path


def read_bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def make_tab(fs, commander=True, key=""):
    """(tab, worker, log) over the fake SFTP surface, optionally in the two-pane mode."""
    worker = SftpWorker(FakeSftpClient(fs))
    log = EventLog()
    wire_worker(worker, log)
    worker.start()
    tab = SftpTab()
    tab.message.connect(lambda *_a: None)
    if key:
        tab.set_session_info(key=key, label="contract", host="192.0.2.10", port=22)
    if commander:
        tab.set_commander(True)
    tab.set_worker(worker)
    return tab, worker, log


def item_by_name(pane, name):
    for i in range(pane.tree.topLevelItemCount()):
        item = pane.tree.topLevelItem(i)
        if item.text(0) == name:
            return item
    return None


class _Drop:
    """A minimal drop event: a position outside the rows, no modifier, a Copy proposal."""

    def position(self):
        return QPointF(-4.0, -4.0)

    def pos(self):
        return self.position().toPoint()

    def modifiers(self):
        from PySide6.QtCore import Qt as _Qt
        return _Qt.KeyboardModifier.NoModifier

    def dropAction(self):
        from PySide6.QtCore import Qt as _Qt
        return _Qt.DropAction.CopyAction

    def acceptProposedAction(self):
        pass


class _RecordingProvider:
    """The four transfer doors of a provider, recorded — the §5 table read without a transport."""

    def __init__(self):
        self.calls = []

    def _log(self, name, args, kw):
        self.calls.append((name, args, kw))
        return 1000 + len(self.calls)

    def queue_upload(self, *a, **kw):
        return self._log("upload", a, kw)

    def queue_download(self, *a, **kw):
        return self._log("download", a, kw)

    def queue_copy(self, *a, **kw):
        return self._log("copy", a, kw)

    def queue_move(self, *a, **kw):
        return self._log("move", a, kw)


# ════════════════════════════════════════════════════════════
# The harness: one remote|local Commander over a REAL OS tree
# ════════════════════════════════════════════════════════════

clear_cfg()
fresh_dir("contract_tree", ("one.txt", b"1\n"), (".hidden", b"h\n"), ("sub/two.txt", b"2\n"))
_fs = FakeSftpFS()
_fs.add_dir("/srv")
_fs.add_dir("/other")
_fs.add_file("/srv/remote.txt", b"R" * 4)
_tab, _worker, _log = make_tab(_fs)
wait_until(lambda: _tab.tree.topLevelItemCount() >= 1, timeout_ms=5000)
_pane_r, _pane_l = _tab.panes[0], _tab.panes[1]

print("== 1. the provider seam (LOCAL_PANE.md §1) ==")

check("§1 the two data sources are declared ONCE and a pane is typed to ONE of them",
      PANE_SOURCES == (SOURCE_REMOTE, SOURCE_LOCAL)
      and isinstance(STAB._SftpPane.provider, property)
      and isinstance(STAB._SftpPane.source, property)
      and _pane_r.source == SOURCE_REMOTE and _pane_r.provider is _worker,
      f"sources={PANE_SOURCES}")

_ok_local = _tab.set_pane_source(_pane_l, SOURCE_LOCAL)
wait_for(lambda: _pane_l.current_dir, timeout_ms=5000)
check("§1 the local provider is the pane's OWN — the container keeps the SESSION's transport",
      _ok_local is True and _pane_l.provider is _pane_l._local_provider is not None
      and _pane_l.provider is not _worker and _tab.worker is _worker
      and _pane_r.provider is _worker,
      f"local={_pane_l._local_provider!r}")

_PROVIDER_METHODS = ("queue_list", "queue_read", "queue_mkdir", "queue_rename", "queue_delete",
                     "queue_normalize", "queue_copy", "queue_move", "queue_upload",
                     "queue_download", "cancel", "shutdown")
check("§1 the local provider answers the SAME method names as the shipped worker",
      all(callable(getattr(LFW.LocalFsWorker, m, None))
          and callable(getattr(SftpWorker, m, None)) for m in _PROVIDER_METHODS),
      str([m for m in _PROVIDER_METHODS if not hasattr(LFW.LocalFsWorker, m)]))

_PROVIDER_SIGNALS = ("list_ready", "task_started", "progress", "task_done", "task_error",
                     "task_cancelled", "read_ready", "normalize_ready")
check("§1 ...and the SAME eight signals — a provider answers every one of them",
      all(hasattr(LFW.LocalFsWorker, s) and hasattr(SftpWorker, s) for s in _PROVIDER_SIGNALS),
      str([s for s in _PROVIDER_SIGNALS if not hasattr(LFW.LocalFsWorker, s)]))
check("§1 the pane binds every signal it declares a slot for (`progress` is the WINDOW's)",
      set(WORKER_SIGNAL_NAMES) <= set(_PROVIDER_SIGNALS)
      and set(_PROVIDER_SIGNALS) - set(WORKER_SIGNAL_NAMES) == {"progress"}
      and all(hasattr(STAB._SftpPane, "_on_" + name) for name in WORKER_SIGNAL_NAMES),
      str(WORKER_SIGNAL_NAMES))

import inspect  # noqa: E402 — the signature clause of §1 (declared here, used once)

_bind_sig = inspect.signature(STAB._SftpPane.bind_worker)
check("§1 `bind_worker(old, new)` keeps its name and its job, and gains ONE keyword (`source`)",
      list(_bind_sig.parameters) == ["self", "old_worker", "new_worker", "source"]
      and _bind_sig.parameters["source"].default == "", str(_bind_sig))

_relisted = []
_orig_relist = _pane_l._relist
_pane_l._relist = lambda *a, **k: _relisted.append(a[:1])
try:
    _tab.relist_dir(_pane_l.current_dir)
finally:
    _pane_l._relist = _orig_relist
check("§1 `SftpTab.relist_dir()` keeps its REMOTE job — a local pane is never re-listed by it",
      _relisted == [], str(_relisted[:2]))

_pane_l._op_tasks[4242] = "junk"
_pane_l._transfer_tasks.add(4242)
_tab.set_pane_source(_pane_l, SOURCE_REMOTE)
check("§1 the pane's bookkeeping belongs to ONE provider — a switch clears every task map",
      4242 not in _pane_l._op_tasks and 4242 not in _pane_l._transfer_tasks)
check("§1 the pane knows the provider it is bound to (the ONE record of the connection)",
      "_bound_provider" in PANE_SRC
      and _pane_l._bound_provider is (_pane_l._local_provider if _pane_l.source == SOURCE_LOCAL
                                      else _worker)
      and _pane_r._bound_provider is _worker
      and _tab.pane_for_provider(_worker) is _pane_r,
      f"local_pane_source={_pane_l.source!r}")
check("§1 a QUEUED answer of the provider a pane LEFT is dropped with it (ids are per provider)",
      "removePostedEvents(self, QEvent.Type.MetaCall)" in PANE_SRC
      and "sig.disconnect(slot)" in PANE_SRC
      and "sig.disconnect(self)" not in PANE_SRC)
check("§1 the way BACK re-binds the SESSION's transport (a waiting, empty pane is the defect)",
      _pane_l.source == SOURCE_REMOTE and _pane_l._waiting is False
      and _pane_l.provider is _worker
      and wait_for(lambda: _pane_l.tree.topLevelItemCount() >= 1, timeout_ms=5000),
      f"waiting={_pane_l._waiting} rows={_pane_l.tree.topLevelItemCount()}")

_tab.set_pane_source(_pane_l, SOURCE_LOCAL)
_pane_l._relist(TREE)
wait_for(lambda: item_by_name(_pane_l, "one.txt") is not None, timeout_ms=5000)

print("== 2. the path dialect (LOCAL_PANE.md §2) ==")

_DECLARED = {"dirname", "join", "basename", "is_root", "is_absolute", "same", "root"}
check("§2 ONE pure object per source, declared once, carrying exactly the table's members",
      POSIX_PATHS.kind == SOURCE_REMOTE and LOCAL_PATHS.kind == SOURCE_LOCAL
      and POSIX_PATHS.is_local is False and LOCAL_PATHS.is_local is True
      and POSIX_PATHS.separator == "/" and LOCAL_PATHS.separator == os.sep
      and {n for n in dir(LOCAL_PATHS)
           if not n.startswith("_") and callable(getattr(LOCAL_PATHS, n))} == _DECLARED,
      str(sorted(_DECLARED)))
check("§2 `display(path)` is the path ITSELF — neither dialect re-spells it",
      not hasattr(LOCAL_PATHS, "display") and not hasattr(POSIX_PATHS, "display")
      and _pane_l.path_label.text() == _pane_l.current_dir)
check("§2 the POSIX side is the shipped `posixpath` rules, byte for byte",
      POSIX_PATHS.dirname("/a/b/c") == "/a/b" and POSIX_PATHS.join("/a", "b") == "/a/b"
      and POSIX_PATHS.basename("/a/b/c") == "c" and POSIX_PATHS.root() == "/"
      and POSIX_PATHS.is_root("/") is True and POSIX_PATHS.is_root("/a") is False)
check("§2 ...and the LOCAL side is the OS's own (`os.path`, the OS separator)",
      LOCAL_PATHS.dirname(os.path.join(TREE, "one.txt")) == TREE
      and LOCAL_PATHS.join(TREE, "x") == os.path.join(TREE, "x")
      and LOCAL_PATHS.basename(os.path.join(TREE, "one.txt")) == "one.txt")
check("§2 `root()` is the platform root on one side and the OS HOME on the other",
      POSIX_PATHS.root() == "/" and LOCAL_PATHS.root() == os.path.expanduser("~"))
check("§2 `is_root()` is the path whose parent is itself — never a bare drive name, never `~`",
      LOCAL_PATHS.is_root(os.path.abspath(os.sep)) is True
      and LOCAL_PATHS.is_root(TREE) is False and LOCAL_PATHS.is_root("~") is False
      and LOCAL_PATHS.is_root(os.path.splitdrive(TREE)[0]) is False)
check("§2 `is_absolute()` counts `~` and `same()` is case-insensitive on the OS disk",
      LOCAL_PATHS.is_absolute("~") is True and POSIX_PATHS.is_absolute("~") is True
      and LOCAL_PATHS.is_absolute("sub") is False
      and POSIX_PATHS.same("/A", "/a") is False
      and LOCAL_PATHS.same(TREE.upper(), TREE.lower() if os.name == "nt" else TREE)
      is (os.name == "nt"))
check("§2 the dialect is a property of the PANE, resolved from its source",
      isinstance(STAB._SftpPane.paths, property)
      and _pane_l.paths is LOCAL_PATHS and _pane_r.paths is POSIX_PATHS
      and dialect_for(SOURCE_LOCAL) is LOCAL_PATHS and dialect_for("nonsense") is POSIX_PATHS)
check("§2 a typed path is resolved by the SOURCE's own side (the provider's `queue_normalize`)",
      "provider.queue_normalize" in PANE_SRC and "queue_normalize" in ENGINE_SRC)
_dialect_src = PANE_SRC[PANE_SRC.index("class PathDialect"):PANE_SRC.index("def local_error_text")]
check("§2 the dialect is PURE — its object holds no Qt, no IO and no i18n",
      "PySide6" not in _dialect_src and "open(" not in _dialect_src and "_t(" not in _dialect_src)

print("== 3. the local surface and its machine codes (LOCAL_PANE.md §3) ==")

_KIND_TABLE = {"queue_list": SW.KIND_LIST, "queue_normalize": SW.KIND_NORMALIZE,
               "queue_read": SW.KIND_READ, "queue_mkdir": SW.KIND_MKDIR,
               "queue_rename": SW.KIND_RENAME, "queue_delete": SW.KIND_DELETE}
check("§3 the task kinds are the SHIPPED vocabulary, imported and never copied",
      set(_KIND_TABLE.values()) == {"list", "normalize", "read", "mkdir", "rename", "delete"}
      and LFW.KIND_LIST is SW.KIND_LIST and LFW.task_payload is SW.task_payload
      and all(callable(getattr(LFW.LocalFsWorker, m, None)) for m in _KIND_TABLE),
      str(sorted(_KIND_TABLE.values())))
check("§3 the four transfer doors are the LOCAL engine: `shutil.copy2` through `.part` + `os.replace`",
      all(callable(getattr(LFW.LocalFsWorker, m, None))
          for m in ("queue_upload", "queue_download", "queue_copy", "queue_move"))
      and "shutil.copy2" in ENGINE_SRC and PART_SUFFIX in ENGINE_SRC
      and "os.replace" in ENGINE_SRC, PART_SUFFIX)

_ONE = item_by_name(_pane_l, "one.txt")
check("§3 the row shape does not move: the FOUR roles of a real local listing",
      _ONE is not None and _ONE.data(0, _pane_l.PATH_ROLE) == os.path.join(TREE, "one.txt")
      and _ONE.data(0, _pane_l.ISDIR_ROLE) in (False, 0)
      and int(_ONE.data(0, _pane_l.SIZE_ROLE)) == 2
      and isinstance(_ONE.data(0, _pane_l.MTIME_ROLE), (int, float))
      and STAB.SftpTab.PATH_ROLE == STAB._SftpPane.PATH_ROLE,
      str(_ONE.data(0, _pane_l.PATH_ROLE) if _ONE else None))
check("§3 ...and the FULL path of a row is built through the pane's own dialect",
      _ONE is not None and _pane_l.paths.same(_ONE.data(0, _pane_l.PATH_ROLE),
                                              _pane_l.paths.join(_pane_l.current_dir, "one.txt")))
check("§3 hidden and system entries are SHOWN (the classic commander)",
      item_by_name(_pane_l, ".hidden") is not None)

# v1.7.5: a session that was never IDENTIFIED (no alias) — the header line's `user@host` fallback.
_fs_named = FakeSftpFS()
_fs_named.add_dir("/srv")
_tab_named, _worker_named, _log_named = make_tab(_fs_named, commander=False)
_tab_named.set_session_info(key="contract-named", label="", host="192.0.2.10", port=22, user="root")
_pane_named = _tab_named.panes[0]

check("§3 a local pane's HEADER LINE names its source (`header_text()`), never the remote waiting line",
      _pane_l.header_text() == i18n.t("sftp.local.this_computer")
      and _pane_l.header_text() != i18n.t("sftp.waiting_connection")
      and _pane_l.header_label.text() == _pane_l.header_text()
      and '"sftp.local.this_computer"' in PANE_SRC,
      _pane_l.header_text())
check("§3 ...while a pane of an UNIDENTIFIED container keeps the shipped waiting wording",
      _pane_r.header_text() == i18n.t("sftp.waiting_connection")
      and _pane_r.header_label.text() == _pane_r.header_text(),
      _pane_r.header_text())
check("§3 ...and falls back to `user@host` when the session has no alias",
      _pane_named.header_text() == "root@192.0.2.10"
      and _pane_named.header_label.text() == "root@192.0.2.10",
      _pane_named.header_text())
_tab_named.set_session_info(key="contract-named", label="contract", host="192.0.2.10",
                            port=22, user="root")
check("§3 ...and the ALIAS wins, re-read the moment the session is identified",
      _pane_named.header_text() == "contract"
      and _pane_named.header_label.text() == "contract",
      _pane_named.header_text())
check("§3 the pane's SOURCE HEADER LINE is CARRIED (the v1.7.5 clause shipped with its widget)",
      "header_label" in CONTRACT and "the pane's FIRST row" in CONTRACT
      and "**`v1.7.5` (SHIPPED):**" in CONTRACT
      and hasattr(_pane_l, "header_label")
      and _pane_l.header_label is _pane_l.source_header_label(),
      "the contract's amendment and its widget ship in ONE slot (ROADMAP v1.7.5, task 3)")
_HEADER_HINT = _pane_l.header_label.sizeHint().height()
_pane_l.header_label.setText("x" * 400)
check("§3 the header line is ONE row: no wrap, no focus, a longer text does not grow it",
      _pane_l.header_label.wordWrap() is False
      and _pane_l.header_label.focusPolicy() == _Qt.FocusPolicy.NoFocus
      and _pane_l.header_label.sizeHint().height() == _HEADER_HINT
      and _HEADER_HINT <= 2 * _pane_l.header_label.fontMetrics().height(),
      f"hint={_HEADER_HINT} grown={_pane_l.header_label.sizeHint().height()} "
      f"font={_pane_l.header_label.fontMetrics().height()}")
_pane_l._sync_header()
check("§3 ...and it is the pane's FIRST widget row, ABOVE the address bar",
      _pane_l.layout().itemAt(0) is not None
      and _pane_l.layout().itemAt(0).widget() is _pane_l.header_label
      and _pane_l.layout().itemAt(1) is not None
      and _pane_l.layout().itemAt(1).layout() is not None
      and _pane_l.layout().itemAt(1).layout().indexOf(_pane_l.path_label) >= 0,
      f"rows={_pane_l.layout().count()}")
check("§3 the transfer row of a local pane is LIVE (rc2 moves bytes through its own provider)",
      _pane_l.btn_up.isEnabled() and _pane_l.btn_refresh.isEnabled()
      and _pane_l.btn_upload.isEnabled() and _pane_l.btn_download.isEnabled())

_CODE_TABLE = {"permission": "sftp.local.permission", "locked": "sftp.local.locked",
               "too_long": "sftp.local.too_long", "missing": "sftp.local.missing",
               "symlink_dir": "sftp.local.symlink_dir", "not_dir": "sftp.local.not_dir",
               "is_dir": "sftp.local.is_dir", "exists": "sftp.local.exists",
               "unreadable": "sftp.local.unreadable"}
check("§3 every machine code of the table maps to the key the table names — declared ONCE",
      all(LFW.LOCAL_ERROR_KEYS.get(code) == key for code, key in _CODE_TABLE.items()),
      str(LFW.LOCAL_ERROR_KEYS))
check("§3 ...and the table is CLOSED: no code can ship without a sentence",
      set(LFW.LOCAL_ERROR_KEYS) == set(_CODE_TABLE) | {LFW.KIND_LIST_PARTIAL})
check("§3 every sentence exists and is non-empty in EVERY language",
      all(str(data.get(key) or "").strip()
          for key in _CODE_TABLE.values() for data in LANGS.values()))
check("§3 a code with no sentence falls back to the SHIPPED generic operation line",
      STAB.local_error_text(SW.task_payload("who_knows", error="x"))
      == i18n.t("sftp.op.error", error="x"))
check("§3 the READ refusals keep the shipped BARE codes (the row markers read them)",
      LFW.READ_ERROR_KEYS[SW.READ_ERROR_BINARY] == "sftp.viewer.binary"
      and LFW.READ_ERROR_KEYS[SW.READ_ERROR_TOO_LARGE] == "sftp.viewer.too_large"
      and LFW.MAX_READ_BYTES == SW.MAX_READ_BYTES)
check("§3 the listing's skipped entries ride ONE declared note, not a refusal",
      LFW.KIND_LIST_PARTIAL == "list_partial"
      and LFW.LOCAL_ERROR_KEYS[LFW.KIND_LIST_PARTIAL] == "sftp.local.skipped"
      and parse_task_payload(LFW.task_payload(LFW.KIND_LIST_PARTIAL, count=2,
                                              names="a, b"))["count"] == 2)

_LINK_SRC = fresh_dir("contract_link", ("real/inside.txt", b"in"))
_SYMLINK_OK = True
try:
    os.symlink(os.path.join(_LINK_SRC, "real"), os.path.join(_LINK_SRC, "link"))
except (OSError, NotImplementedError, AttributeError):
    _SYMLINK_OK = False   # Windows without the privilege: the rule is asserted over the walk
if _SYMLINK_OK:
    _sym_msgs = []
    _pane_l.message.connect(_sym_msgs.append)
    _pane_l._relist(_LINK_SRC)
    wait_for(lambda: item_by_name(_pane_l, "link") is not None, timeout_ms=5000)
    _pane_l._navigate(os.path.join(_LINK_SRC, "link"))
    check("§3 a directory symlink is listed but REFUSED when it is entered (one sentence)",
          wait_for(lambda: i18n.t("sftp.local.symlink_dir") in _sym_msgs, timeout_ms=5000),
          str(_sym_msgs)[-120:])
else:
    check("§3 a directory symlink is never followed (the refusal is DECLARED on this platform)",
          LFW.LOCAL_SYMLINK_DIR == "symlink_dir" and "islink" in ENGINE_SRC,
          "the platform refused to create a link — the rule is asserted over the walk")

print("== 4. the source switch and its two refusals (LOCAL_PANE.md §4) ==")

check("§4 the switch is an action of the SECOND pane's ADDRESS ROW, not a container control",
      _pane_l.source_switch.parent() is _pane_l
      and "source_switch = _SourceSwitch()" in PANE_SRC)
_bare = SftpTab()
check("§4 a session opens with TWO REMOTE panes and the switch is OFF while there is ONE",
      _bare.panes[0].source == SOURCE_REMOTE
      and _bare.can_use_local(_bare.panes[0]) is False
      and not _bare.source_switch.isEnabled())
_bare_msgs = []
_bare.message.connect(_bare_msgs.append)
check("§4 ...and the refused ask is SAID in ONE sentence, never a silent no-op",
      _bare.set_pane_source(_bare.panes[0], SOURCE_LOCAL) is False
      and _bare_msgs[-1:] == [i18n.t("sftp.local.unavailable")], str(_bare_msgs)[-120:])
check("§4 with TWO panes the SECOND one may go local and the FIRST one may NOT",
      _tab.can_use_local(_pane_l) is True and _tab.can_use_local(_pane_r) is False)
check("§4 the cwd follow stays the remote panes' alone — a local listing never follows",
      _pane_l.follow_directory("/srv") is False and _tab.follow_directory("/srv") is False,
      "the two-pane mode turns the follow off by construction")
check("§4 the way back is the SESSION's opening rule, NEVER the other dialect's path",
      "keep = self._current_dir" not in PANE_SRC
      and "self._restored = target == SOURCE_LOCAL" in PANE_SRC
      and _tab.set_pane_source(_pane_l, SOURCE_REMOTE) is True
      and _pane_l.current_dir == "/" and _pane_l.source == SOURCE_REMOTE,
      f"dir={_pane_l.current_dir!r}")
check("§4 the OS look this pane had SURVIVES the round trip (the object and its provider too)",
      os.path.normcase(_pane_l._local_dir) == os.path.normcase(TREE)
      and _tab.set_pane_source(_pane_l, SOURCE_LOCAL) is True
      and os.path.normcase(_pane_l.current_dir) == os.path.normcase(TREE)
      and _pane_l._local_provider.isRunning(),
      f"local_dir={_pane_l._local_dir!r} dir={_pane_l.current_dir!r}")
check("§4 the recovery of a GONE remembered directory lists the SOURCE's own root",
      'self._relist(self.paths.root())' in PANE_SRC
      and 'fallback=self.paths.root()' in PANE_SRC
      and 'self._relist("/")\n                self._on_task_finished' not in PANE_SRC)
check("§4 the permanent-delete warning is the LOCAL pane's (there is no recycle bin)",
      '"sftp.local.delete_confirm"' in PANE_SRC
      and all(str(data.get("sftp.local.delete_confirm") or "").strip()
              for data in LANGS.values())
      and "recycle" in LANGS["en"]["sftp.local.delete_confirm"].lower())
check("§4 turning the Commander OFF destroys the second pane through the shipped path",
      _tab.set_commander(False) is True and len(_tab.panes) == 1
      and _pane_l._local_provider is None and _tab.panes[0].provider is _worker)

print("== 5. the cross-pane dispatch (LOCAL_PANE.md §5) ==")

_rec = _RecordingProvider()
_rec_pane = _tab.panes[0]
_rec_pane._queue_batch_item(_rec, SOURCE_REMOTE, SOURCE_REMOTE, KIND_COPY, "/srv/a", "/srv/b",
                            "a", 0)
check("§5 remote→remote keeps the SHIPPED `queue_copy` / `queue_move` (untouched)",
      _rec.calls[-1][0] == "copy" and _rec.calls[-1][1] == ("/srv/a", "/srv/b", "a"), str(_rec.calls[-1]))
_rec_pane._queue_batch_item(_rec, SOURCE_LOCAL, SOURCE_REMOTE, KIND_COPY, "/l/a", "/srv/b", "a", 0)
check("§5 local→remote is the SESSION worker's SHIPPED `queue_upload`",
      _rec.calls[-1][0] == "upload" and _rec.calls[-1][2].get("remote_name") == "a")
_rec_pane._queue_batch_item(_rec, SOURCE_REMOTE, SOURCE_LOCAL, KIND_COPY, "/srv/a", "/l/b", "a", 7)
check("§5 remote→local is the SHIPPED `queue_download` (atomic on the OS disk)",
      _rec.calls[-1][0] == "download" and _rec.calls[-1][1] == ("/srv/a", "/l/b", 7)
      and _rec.calls[-1][2].get("local_name") == "a")
_rec_pane._queue_batch_item(_rec, SOURCE_LOCAL, SOURCE_LOCAL, KIND_MOVE, "/l/a", "/l/b", "a", 0)
check("§5 local→local is the LOCAL engine of `modules/local_fs_worker.py`",
      _rec.calls[-1][0] == "move" and _rec.calls[-1][1] == ("/l/a", "/l/b", "a"))
check("§5 the DISPATCH resolves the provider by the PAIR (a remote destination is the session's)",
      _rec_pane._batch_provider(_rec_pane, SOURCE_REMOTE) is _worker
      and _rec_pane._batch_provider(_rec_pane, SOURCE_LOCAL) is _worker)
check("§5 ONE closing report serves all four cases (the shipped counter pair, no local variant)",
      "sftp.cmd.copy_report" in PANE_SRC and "sftp.cmd.move_report" in PANE_SRC)
check("§5 the batch bookkeeping is per SOURCE: `_op_targets` maps a task to (pane, directory)",
      "_op_targets[task_id]" in PANE_SRC or "_op_targets[tid]" in PANE_SRC
      or "self._op_targets[task_id] = (target_pane, target_dir)" in PANE_SRC)
check("§5 ...and the re-list goes through THAT pane's dialect (a remote answer never lists the OS)",
      "def relist_pane" in PANE_SRC and "self.relist_dir(path)" in PANE_SRC
      and "pane.paths.same(pane.current_dir, path)" in PANE_SRC)
check("§5 a MOVE that would cross the two SOURCES is REFUSED with ONE sentence",
      'kind == KIND_MOVE and src != dst' in PANE_SRC
      and '"sftp.local.move_cross_source"' in PANE_SRC
      and all(str(data.get("sftp.local.move_cross_source") or "").strip()
              for data in LANGS.values()))

# a LOCAL→REMOTE copy runs on the SESSION's worker: the pane BOUND to that transport counts it
_tab3, _worker3, _log3 = make_tab(_fs)
_tab3.set_session_info(key="contract-session", label="contract", host="192.0.2.10", port=22)
wait_for(lambda: _tab3.tree.topLevelItemCount() >= 1, timeout_ms=5000)
_p3r, _p3l = _tab3.panes[0], _tab3.panes[1]
_tab3.set_pane_source(_p3l, SOURCE_LOCAL)
_UP_SRC = fresh_dir("contract_up_src", ("up.txt", b"UP\n"))
_p3l._relist(_UP_SRC)
wait_for(lambda: item_by_name(_p3l, "up.txt") is not None, timeout_ms=5000)
_p3r._relist("/srv")
wait_for(lambda: item_by_name(_p3r, "remote.txt") is not None, timeout_ms=5000)
_p3l.tree.setCurrentItem(item_by_name(_p3l, "up.txt"))
_p3msgs = []
_tab3.message.connect(_p3msgs.append)
_p3l._cmd_copy()
check("§5 a batch that runs on the SESSION's transport is COUNTED by the pane bound to it",
      bool(_p3r._op_batches) and not _p3l._op_batches
      and bool(_p3r._op_tasks) and not _p3l._op_tasks,
      f"remote={len(_p3r._op_batches)} local={len(_p3l._op_batches)}")
check("§5 ...and it closes with the SHIPPED report of the pane that really changed",
      wait_for(lambda: "/srv/up.txt" in _fs.files, timeout_ms=5000)
      and wait_for(lambda: any(str(m).startswith(i18n.t("sftp.cmd.copy_report", done=1, skipped=0, failed=0))
                               for m in _p3msgs), timeout_ms=5000), str(_p3msgs)[-140:])
_tab3.release()
_worker3.shutdown()

print("== 6. the recursive local side (LOCAL_PANE.md §6) ==")

check("§6 the bounds are the SHIPPED objects, imported and never copied",
      LFW.MAX_TREE_ENTRIES is MAX_TREE_ENTRIES is SW.MAX_TREE_ENTRIES
      and LFW.MAX_TREE_DEPTH is MAX_TREE_DEPTH is SW.MAX_TREE_DEPTH
      and int(MAX_TREE_ENTRIES) == 5000 and int(MAX_TREE_DEPTH) == 32,
      f"{MAX_TREE_ENTRIES}/{MAX_TREE_DEPTH}")
check("§6 every file of a tree is atomic and a copy is ADDITIVE (a merge, never a delete)",
      "shutil.copy2" in ENGINE_SRC and "os.replace" in ENGINE_SRC
      and PART_SUFFIX in ENGINE_SRC and "_LocalPartial" in ENGINE_SRC)
check("§6 an interrupted tree is REPORTED through the shipped partial payload with its counters",
      parse_task_payload(LFW.task_payload(PARTIAL_CODE, copied=3, path="/x", error="boom"))["copied"] == 3
      and "PARTIAL_CODE" in ENGINE_SRC)
check("§6 a directory source is carried as a WHOLE tree on the engine (a file source untouched)",
      "def _copy_tree" in ENGINE_SRC and "def _move_tree" in ENGINE_SRC
      and "def _walk_tree" in ENGINE_SRC and "def _walk_into" in ENGINE_SRC)
check("§6 a failed tree over its bound is refused BEFORE a byte crosses",
      TREE_ERROR_TOO_BIG == SW.TREE_ERROR_TOO_BIG and "MAX_TREE_ENTRIES" in ENGINE_SRC
      and "MAX_TREE_DEPTH" in ENGINE_SRC)

_eng = LFW.LocalFsWorker(root=WORK)
_elog = EventLog()
wire_worker(_eng, _elog)
_eng.start()
_SRC = fresh_dir("contract_eng_src", ("top.txt", b"top\n"), ("inner/one.txt", b"1\n"))
_DST = fresh_dir("contract_eng_dst", ("keep.txt", b"keep\n"))
_t = _eng.queue_copy(_SRC, _DST, "tree")
wait_for(lambda: bool(_elog.of_kind("done", _t)) or bool(_elog.of_kind("error", _t)), timeout_ms=5000)
check("§6 a REAL local tree copy lands byte for byte, atomically and additively",
      read_bytes(os.path.join(_DST, "tree", "inner", "one.txt")) == b"1\n"
      and read_bytes(os.path.join(_DST, "keep.txt")) == b"keep\n"
      and not [n for n in os.listdir(os.path.join(_DST, "tree")) if n.endswith(PART_SUFFIX)],
      str(sorted(os.listdir(_DST))))
_MOVED_FROM = fresh_dir("contract_eng_move", ("sub/leaf.txt", b"leaf\n"))
_t = _eng.queue_move(_MOVED_FROM, _DST, "moved")
wait_for(lambda: bool(_elog.of_kind("done", _t)), timeout_ms=5000)
check("§6 a move's emptied source directories are removed last (the source tree is gone)",
      read_bytes(os.path.join(_DST, "moved", "sub", "leaf.txt")) == b"leaf\n"
      and not os.path.exists(_MOVED_FROM))
_pin_entries, _pin_depth = LFW.MAX_TREE_ENTRIES, LFW.MAX_TREE_DEPTH
try:
    LFW.MAX_TREE_ENTRIES = 1
    _TOO_BIG_DST = fresh_dir("contract_eng_big")
    _t = _eng.queue_copy(_SRC, _TOO_BIG_DST, "tree")
    wait_for(lambda: bool(_elog.of_kind("error", _t)), timeout_ms=5000)
    _bound = parse_task_payload([e[3] for e in _elog.of_kind("error", _t)][0])
    check("§6 ...and the refusal NAMES the bound it hit (the payload of the shipped code)",
          _bound.get("code") == TREE_ERROR_TOO_BIG and int(_bound.get("limit") or 0) == 1,
          str(_bound)[:120])
finally:
    LFW.MAX_TREE_ENTRIES, LFW.MAX_TREE_DEPTH = _pin_entries, _pin_depth
check("§6 a directory symlink is never followed by the walk (the shipped rule)",
      "islink" in ENGINE_SRC and "skip" in ENGINE_SRC.lower())
_eng.shutdown()
check("§6 the engine thread stops inside its budget (a live QThread is a crash, §4.8)",
      not _eng.isRunning())

print("== 7. the drag & drop in both directions (LOCAL_PANE.md §7) ==")

_DRAG_TREE = fresh_dir("contract_drag", ("top.txt", b"top\n"))
_lpane = _tab.panes[-1] if len(_tab.panes) > 1 else None
_tab2, _worker2, _log2 = make_tab(_fs)
_lpane = _tab2.panes[1]
_tab2.set_pane_source(_lpane, SOURCE_LOCAL)
_db_msgs = []
_tab2.message.connect(_db_msgs.append)
_lpane._relist(_DRAG_TREE)
wait_for(lambda: item_by_name(_lpane, "top.txt") is not None, timeout_ms=5000)
_mime = _lpane.tree.drag_mime(item_by_name(_lpane, "top.txt"))
_payload = pane_payload(_mime)
check("§7 a LOCAL row dragged OUT hands a REAL OS path (`text/uri-list` beside `text/plain`)",
      _mime is not None and _mime.hasFormat("text/uri-list") and _mime.hasUrls()
      and os.path.normcase(os.path.normpath(_mime.urls()[0].toLocalFile()))
      == os.path.normcase(os.path.normpath(os.path.join(_DRAG_TREE, "top.txt"))),
      str(_mime.text()) if _mime else "no mime")
check("§7 ...and the payload keeps the pane identity and DECLARES the source dialect",
      _mime is not None and _mime.hasFormat(PANE_DRAG_MIME)
      and _payload is not None and _payload["source"] == SOURCE_LOCAL
      and _payload["path"] == os.path.join(_DRAG_TREE, "top.txt")
      and {"session", "pane", "path", "source"} <= set(_payload),
      str(_payload))
check("§7 a REMOTE row keeps the shipped payload and offers NO OS path to a foreign app",
      _tab2.panes[0].tree.drag_mime(item_by_name(_tab2.panes[0], "srv")) is not None
      and not _tab2.panes[0].tree.drag_mime(item_by_name(_tab2.panes[0], "srv")).hasUrls())
check("§7 the drop is resolved by the WIDGET under the cursor (a pane's own child pairs to it)",
      _tab2._pane_for_widget(_lpane.tree) is _lpane
      and _tab2._pane_for_widget(_tab2.panes[0].tree) is _tab2.panes[0])
_DROP_DST = fresh_dir("contract_drop")
_lpane._relist(_DROP_DST)
wait_for(lambda: _lpane.current_dir == _DROP_DST, timeout_ms=5000)
_before = set(_fs.files)
_lpane._on_drop([os.path.join(_DRAG_TREE, "top.txt")], _DROP_DST)
check("§7 an Explorer drop on the LOCAL pane is a LOCAL copy, never an upload",
      wait_for(lambda: read_bytes(os.path.join(_DROP_DST, "top.txt")) == b"top\n", timeout_ms=5000)
      and set(_fs.files) == _before, str(sorted(_fs.files)))
_check_dst = set(_fs.files)
_tab2.panes[0]._relist("/other")
wait_for(lambda: _tab2.panes[0].current_dir == "/other", timeout_ms=5000)
_tab2.panes[0]._on_drop([os.path.join(_DRAG_TREE, "top.txt")], "/other")
check("§7 ...while a drop on the REMOTE pane stays the shipped upload",
      wait_for(lambda: "/other/top.txt" in _fs.files, timeout_ms=5000)
      and bytes(_fs.files["/other/top.txt"]) == b"top\n" and _check_dst != set(_fs.files))

print("== 8. the refactor boundary (LOCAL_PANE.md §8) ==")

check("§8 the remote pane's behaviour does not move: it never stores a provider of its own",
      _tab2.panes[0]._local_provider is None
      and _tab2.panes[0].provider is _worker2
      and "def worker" in PANE_SRC)
check("§8 the ONE changed clause of the closed contract is the LOCAL exception, asserted beside it",
      "a pane never stores one" in PANES_CONTRACT and "reads the container's" in PANES_CONTRACT
      and "LOCAL_PANE.md §1" in PANE_SRC
      and _lpane._local_provider is not None,
      "SFTP_PANES.md §1 keeps its sentence for the remote pane")
check("§8 the pane's own `release()` shuts the LOCAL provider down (the §9 teardown clause)",
      "def release" in PANE_SRC and "shutdown_provider" in PANE_SRC
      and _lpane._local_provider is not None)
_prov = _lpane._local_provider
_lpane.release()
check("§8 ...and the released pane keeps no live thread",
      _prov.isRunning() is False and _lpane._local_provider is None)
check("§8 an orphaned provider is DETACHED from the pane before the registry holds it",
      "setParent(None)" in ENGINE_SRC
      and "register_orphan_local_provider" in ENGINE_SRC)
_holder = QWidget()
_orphan = LFW.LocalFsWorker(root=WORK, parent=_holder)
_orphan.start()
LFW.register_orphan_local_provider(_orphan)
check("§8 ...so the registry's promise holds: the thread outlives the widget that owned it",
      _orphan.parent() is None and _orphan in LFW._orphan_providers,
      f"parent={_orphan.parent()}")
_orphan.shutdown(2500)
wait_for(lambda: _orphan not in LFW._orphan_providers, timeout_ms=8000)

print("== 9. the release state (LOCAL_PANE.md §9) ==")

check_i18n_parity(LANGS)
check_i18n_format(LANGS)
check_release_state(ROOT)
check("§9 the version pin is the release this audit ships with",
      releases_at_least(EXPECTED_APP_VERSION, "1.7.4"), EXPECTED_APP_VERSION)
check("§9 the i18n pin counts the shipped keys (the local pane's 18 + the v1.7.5 slot's 4 + "
      "the v1.7.5.1 slot's 6 + the v1.8 elevated pane's 20 + the v1.8.1 trust surface's 41 + the ONE "
      "of v1.8.1.1) and v1.8.2 adds SIXTEEN: the library file — the History door, the backup ring and the import/export pair — and v1.8.3 adds TWENTY-THREE: the Plugins window (its chrome, its three columns and its export)",
      EXPECTED_I18N_KEYS == 897 + 17 + 1 + 4 + 6 + 20 + 41 + 1 + 16 + 23, str(EXPECTED_I18N_KEYS))
check("§9 VERSION_FORMAT did NOT move (a path is never written into a project)",
      __import__("version").VERSION_FORMAT == "0.9")
check("§9 no new dependency was added for the local pane (the four pinned ones)",
      all(f"{d}>=" in open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read()
          for d in ("PySide6", "paramiko", "keyring", "wcwidth")))
check("§9 the frozen contract and its topical files are in the repository",
      os.path.exists(os.path.join(ROOT, "LOCAL_PANE.md"))
      and os.path.exists(os.path.join(ROOT, "tests", "test_local_pane.py")))
check("§9 the contract carries its own acceptance for this slot (the audit is named there)",
      "the clause-by-clause audit of THIS document" in CONTRACT
      and "per clause group" in CONTRACT
      and "ROADMAP.md` losing the" in CONTRACT)
check("§9 the LOCAL ERROR table is the contract's, read back clause by clause",
      all(key.startswith("sftp.local.") for key in _CODE_TABLE.values())
      and len([k for k in LANGS["en"] if k.startswith("sftp.local.")]) == 18,
      f"{len([k for k in LANGS['en'] if k.startswith('sftp.local.')])} keys")

_tab2.release()
_worker2.shutdown()
_tab_named.release()
_worker_named.shutdown()
_tab.release()
_worker.shutdown()
finish()
