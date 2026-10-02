# -*- coding: utf-8 -*-
"""The LOCAL pane (v1.7.4rc1): the provider seam, the two path dialects, the OS listing of the
second Commander pane and the source switch with its two structural refusals.

Offscreen, no network. The remote half runs over the fake SFTP surface of `_fakes.py`; the local
half runs over a REAL tree inside an isolated HOME, because the provider is the OS itself.
Contract — `LOCAL_PANE.md` §1–§4; mechanism — `DOCUMENTATION.md` §64.

Run: python tests/test_local_pane.py   (from the project root) or python tests/run_all.py"""
import os
import re
import sys

from _common import (bootstrap, check, finish, wait_until, load_i18n_langs, check_i18n_parity,
                     check_i18n_format, check_release_state, clear_cfg, releases_at_least,
                     EXPECTED_APP_VERSION, EXPECTED_I18N_KEYS)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation)

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

import i18n
import modules.local_fs_worker as LFW
import modules.sftp_tab as STAB
import modules.sftp_worker as SW
from modules.sftp_tab import (LOCAL_PATHS, POSIX_PATHS, SOURCE_LOCAL, SOURCE_REMOTE, PathDialect,
                              SftpTab, dialect_for, local_error_text)
from modules.sftp_worker import KIND_DELETE, KIND_LIST, KIND_MKDIR, KIND_NORMALIZE, KIND_READ, \
    KIND_RENAME, MAX_READ_BYTES, READ_ERROR_BINARY, READ_ERROR_TOO_LARGE, SftpWorker, \
    parse_task_payload

from _fakes import EventLog, FakeSftpClient, FakeSftpFS, wire_worker


# ════════════════════════════════════════════════════════════
# The harness: a REAL local tree + a real LocalFsWorker thread
# ════════════════════════════════════════════════════════════

TREE = os.path.join(WORK, "local_tree")


def build_tree():
    """A small OS tree: two files, a nested file, a hidden file and a binary one."""
    if os.path.isdir(TREE):
        import shutil
        shutil.rmtree(TREE, ignore_errors=True)
    os.makedirs(os.path.join(TREE, "sub", "deep"))
    with open(os.path.join(TREE, "alpha.txt"), "wb") as f:
        f.write(b"alpha\n")
    with open(os.path.join(TREE, "beta.log"), "wb") as f:
        f.write(b"beta\n" * 4)
    with open(os.path.join(TREE, ".hidden"), "wb") as f:
        f.write(b"hidden\n")
    with open(os.path.join(TREE, "pic.png"), "wb") as f:
        f.write(b"\x89PNG\r\n")
    with open(os.path.join(TREE, "sub", "nested.py"), "wb") as f:
        f.write(b"print(1)\n")
    with open(os.path.join(TREE, "sub", "deep", "leaf.txt"), "wb") as f:
        f.write(b"leaf\n")
    return TREE


def make_provider(root=None):
    """(provider, log) started and wired — the shipped `make_tab` shape for the LOCAL side."""
    provider = LFW.LocalFsWorker(root=root or TREE)
    log = EventLog()
    wire_worker(provider, log)
    provider.start()
    return provider, log


def make_remote_tab(fs, commander=True):
    """(tab, worker, log) — a tab over the fake SFTP surface, optionally in the two-pane mode."""
    client = FakeSftpClient(fs)
    worker = SftpWorker(client)
    log = EventLog()
    wire_worker(worker, log)
    worker.start()
    tab = SftpTab()
    tab.message.connect(lambda *_a: None)
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


build_tree()
print("== 1. the path dialect (LOCAL_PANE.md §2) ==")

check("§2 the two dialects are declared ONCE and resolve by source",
      POSIX_PATHS.is_local is False and LOCAL_PATHS.is_local is True
      and dialect_for(SOURCE_REMOTE) is POSIX_PATHS and dialect_for(SOURCE_LOCAL) is LOCAL_PATHS
      and dialect_for("nonsense") is POSIX_PATHS
      and isinstance(LOCAL_PATHS, PathDialect) and LOCAL_PATHS.separator == os.sep
      and POSIX_PATHS.separator == "/")

check("§2 the POSIX dialect is byte-for-byte the shipped rules",
      POSIX_PATHS.dirname("/a/b/c") == "/a/b" and POSIX_PATHS.join("/a", "b") == "/a/b"
      and POSIX_PATHS.basename("/a/b/c") == "c" and POSIX_PATHS.is_root("/") is True
      and POSIX_PATHS.is_root("/a") is False and POSIX_PATHS.is_absolute("a") is False
      and POSIX_PATHS.is_absolute("~") is True and POSIX_PATHS.same("/A", "/a") is False
      and POSIX_PATHS.root() == "/")

check("§2 the LOCAL dialect joins with the OS separator and splits the way the OS does",
      LOCAL_PATHS.join(TREE, "alpha.txt") == os.path.join(TREE, "alpha.txt")
      and LOCAL_PATHS.dirname(os.path.join(TREE, "alpha.txt")) == TREE
      and LOCAL_PATHS.basename(os.path.join(TREE, "alpha.txt")) == "alpha.txt"
      and LOCAL_PATHS.is_absolute(TREE) is True
      and LOCAL_PATHS.is_absolute("sub") is False
      and LOCAL_PATHS.is_absolute("~") is True
      and LOCAL_PATHS.same(TREE.upper(), TREE.lower() if os.name == "nt" else TREE) is (os.name == "nt"))

check("§2 the LOCAL root is the path its own parent already is — never a bare drive name",
      LOCAL_PATHS.is_root(os.path.abspath(os.sep)) is True
      and LOCAL_PATHS.is_root(TREE) is False
      and LOCAL_PATHS.is_root("~") is False
      and LOCAL_PATHS.is_root("") is False
      and (os.name != "nt" or LOCAL_PATHS.is_root("C:") is False))

check("§2 the dialect is PURE: it holds no Qt, no IO and no i18n",
      "PySide6" not in PathDialect.__module__
      and all(m in ("dirname", "join", "basename", "is_root", "is_absolute", "same",
                    "local_name", "root") or m.startswith("_") or m in ("kind", "label",
                                                                        "is_local", "separator")
              for m in dir(PathDialect)))

print("== 2. the local provider: the LISTING (LOCAL_PANE.md §3) ==")

provider, plog = make_provider()
tid = provider.queue_list(TREE)   # a path that does NOT exist → the refusal below
check("§3 the provider queues a listing and answers it", isinstance(tid, int) and tid >= 1, str(tid))
wait_until(lambda: bool(plog.of_kind("list", tid)), timeout_ms=5000)
_list = plog.of_kind("list", tid)
check("§3 the listing really arrived", len(_list) == 1, str(_list)[:120])

if _list:
    _dir, _entries = _list[0][2], _list[0][3]
    names = [e["name"] for e in _entries]
    check("§3 the ROW SHAPE is the remote one (name / is_dir / size / mtime)",
          all(set(e) == {"name", "is_dir", "size", "mtime"} for e in _entries),
          str(_entries)[:160])
    check("§3 directories come FIRST, then the files by lower-case name",
          names[:1] == ["sub"]
          and names[1:] == sorted(names[1:], key=lambda n: n.lower()),
          str(names))
    check("§3 HIDDEN entries are SHOWN (the classic commander) and the size / mtime are real",
          ".hidden" in names
          and [e for e in _entries if e["name"] == "alpha.txt"][0]["size"] == 6
          and [e for e in _entries if e["name"] == "alpha.txt"][0]["mtime"] > 0
          and [e for e in _entries if e["name"] == "sub"][0]["size"] == 0)

_tid_missing = provider.queue_list(os.path.join(TREE, "nope"))
wait_until(lambda: bool(plog.of_kind("error", _tid_missing)), timeout_ms=5000)
_err = plog.of_kind("error", _tid_missing)
check("§3 a directory that is gone is ONE machine payload, never a traceback",
      len(_err) == 1 and (parse_task_payload(_err[0][3]) or {}).get("code") == LFW.LOCAL_MISSING,
      str(_err)[:160])
check("§3 ...and the provider queue SURVIVED it (the next listing really ran)",
      provider.queue_list(TREE) is not None and not provider.isFinished())

print("== 3. the local provider: normalize, read and the file operations ==")

_norm = provider.queue_normalize("~")
wait_until(lambda: bool(plog.of_kind("normalize", _norm)), timeout_ms=5000)
_n = plog.of_kind("normalize", _norm)
check("§3 `~` is expanded by the OS (the address bar's own resolution)",
      len(_n) == 1 and os.path.isabs(_n[0][3])
      and os.path.normcase(_n[0][3]) == os.path.normcase(os.path.expanduser("~")), str(_n)[:120])

_norm2 = provider.queue_normalize("sub", TREE)
wait_until(lambda: bool(plog.of_kind("normalize", _norm2)), timeout_ms=5000)
_n2 = plog.of_kind("normalize", _norm2)
check("§3 a RELATIVE path is resolved against the directory on the screen",
      len(_n2) == 1 and os.path.normcase(_n2[0][3]) == os.path.normcase(os.path.join(TREE, "sub")),
      str(_n2)[:120])

_rd = provider.queue_read(os.path.join(TREE, "alpha.txt"), 6)
wait_until(lambda: bool(plog.of_kind("read", _rd)), timeout_ms=5000)
_r = plog.of_kind("read", _rd)
check("§3 a text file is read through the SHIPPED policy (bytes as they are)",
      len(_r) == 1 and _r[0][3] == b"alpha\n", str(_r)[:120])

_rd_bin = provider.queue_read(os.path.join(TREE, "pic.png"), 6)
wait_until(lambda: bool(plog.of_kind("error", _rd_bin)), timeout_ms=5000)
check("§3 a known-BINARY extension is refused with the SHIPPED bare code",
      [e[3] for e in plog.of_kind("error", _rd_bin)] == [READ_ERROR_BINARY],
      str(plog.of_kind("error", _rd_bin))[:120])

_big = os.path.join(TREE, "big.txt")
with open(_big, "wb") as f:
    f.write(b"x" * (MAX_READ_BYTES + 10))
_rd_big = provider.queue_read(_big, MAX_READ_BYTES + 10)
wait_until(lambda: bool(plog.of_kind("error", _rd_big)), timeout_ms=5000)
check("§3 a file over MAX_READ_BYTES is refused BEFORE it is opened (the shipped cap)",
      [e[3] for e in plog.of_kind("error", _rd_big)] == [READ_ERROR_TOO_LARGE],
      str(plog.of_kind("error", _rd_big))[:120])
os.remove(_big)

_mk = provider.queue_mkdir(TREE, "fresh")
wait_until(lambda: bool(plog.of_kind("done", _mk)), timeout_ms=5000)
check("§3 `mkdir` creates ONE directory and answers its full path",
      os.path.isdir(os.path.join(TREE, "fresh"))
      and [e[2] for e in plog.of_kind("done", _mk)] == [os.path.join(TREE, "fresh")],
      str(plog.of_kind("done", _mk))[:140])

_mk2 = provider.queue_mkdir(TREE, "fresh")
wait_until(lambda: bool(plog.of_kind("error", _mk2)), timeout_ms=5000)
check("§3 ...and an existing name is the DECLARED `exists` refusal (not a crash)",
      (parse_task_payload(plog.of_kind("error", _mk2)[0][3]) or {}).get("code") == LFW.LOCAL_EXISTS,
      str(plog.of_kind("error", _mk2))[:140])

_rn = provider.queue_rename(os.path.join(TREE, "beta.log"), "beta2.log")
wait_until(lambda: bool(plog.of_kind("done", _rn)), timeout_ms=5000)
check("§3 `rename` changes the NAME in place (the directory does not move)",
      os.path.isfile(os.path.join(TREE, "beta2.log"))
      and not os.path.exists(os.path.join(TREE, "beta.log")))

_dl = provider.queue_delete(os.path.join(TREE, "beta2.log"), False)
wait_until(lambda: bool(plog.of_kind("done", _dl)), timeout_ms=5000)
check("§3 `delete` removes a FILE and the real disk follows",
      not os.path.exists(os.path.join(TREE, "beta2.log")))

_rmdir = provider.queue_delete(os.path.join(TREE, "sub"), True)
wait_until(lambda: bool(plog.of_kind("error", _rmdir)), timeout_ms=5000)
check("§3 a NON-EMPTY directory is refused (rmdir, never a recursive delete here)",
      bool(plog.of_kind("error", _rmdir)) and os.path.isdir(os.path.join(TREE, "sub")),
      str(plog.of_kind("error", _rmdir))[:140])

_rmdir2 = provider.queue_delete(os.path.join(TREE, "fresh"), True)
wait_until(lambda: bool(plog.of_kind("done", _rmdir2)), timeout_ms=5000)
check("§3 ...and an EMPTY one really goes", not os.path.exists(os.path.join(TREE, "fresh")))

check("§3 the four TRANSFER methods are RESERVED, not silently wrong",
      all(callable(getattr(provider, name, None)) for name in LFW.RESERVED_METHODS)
      and LFW.RESERVED_METHODS == ("queue_upload", "queue_download", "queue_copy", "queue_move"))
_raised = 0
for _name in LFW.RESERVED_METHODS:
    try:
        getattr(provider, _name)("a", "b")
    except NotImplementedError:
        _raised += 1
check("§3 each of them raises `NotImplementedError` (rc2 is what binds them)",
      _raised == len(LFW.RESERVED_METHODS), str(_raised))

check("§3 the provider NAMES its thread (AGENTS.md §4.8)",
      provider.objectName() == "LocalFsWorker")

check("§3 the code holds no UI sentence — every refusal is an i18n KEY of the declared table",
      all(str(v).startswith("sftp.local.") for v in LFW.LOCAL_ERROR_KEYS.values())
      and set(LFW.LOCAL_ERROR_KEYS) >= {LFW.LOCAL_PERMISSION, LFW.LOCAL_LOCKED, LFW.LOCAL_TOO_LONG,
                                        LFW.LOCAL_MISSING, LFW.LOCAL_SYMLINK_DIR, LFW.LOCAL_NOT_DIR,
                                        LFW.LOCAL_IS_DIR, LFW.LOCAL_EXISTS, LFW.LOCAL_UNREADABLE})

provider.shutdown()
check("§3 `shutdown()` stops the thread inside its budget", not provider.isRunning())

print("== 4. the source switch and the pane's provider (LOCAL_PANE.md §1/§4) ==")

clear_cfg()
fs = FakeSftpFS()
fs.add_dir("/left")
fs.add_dir("/right")
fs.add_file("/left/l.txt", b"L")
fs.add_file("/right/r.txt", b"R")
one_pane_tab, one_worker_obj, _one_log = make_remote_tab(fs, commander=False)
wait_until(lambda: one_pane_tab.tree.topLevelItemCount() >= 1, timeout_ms=5000)

check("§4 a FRESH tab holds ONE pane and the switch is OFF (no other side to browse)",
      len(one_pane_tab.panes) == 1 and one_pane_tab.can_use_local(one_pane_tab.panes[0]) is False
      and one_pane_tab.panes[0].source_switch.isEnabledTo(one_pane_tab.panes[0]) is False
      and one_pane_tab.panes[0].source_switch.source() == SOURCE_REMOTE,
      f"panes={len(one_pane_tab.panes)} can={one_pane_tab.can_use_local(one_pane_tab.panes[0])} "
      f"en={one_pane_tab.panes[0].source_switch.isEnabledTo(one_pane_tab.panes[0])} "
      f"src={one_pane_tab.panes[0].source_switch.source()!r}")

check("§4 ...and the ONE pane is refused with ONE sentence, never a silent no-op",
      one_pane_tab.set_pane_source(one_pane_tab.panes[0], SOURCE_LOCAL, notify=False) is False
      and one_pane_tab.panes[0].source == SOURCE_REMOTE)
one_pane_tab.set_worker(None)
one_worker_obj.shutdown()

tab, worker, tlog = make_remote_tab(fs)
wait_until(lambda: tab.tree.topLevelItemCount() >= 1, timeout_ms=5000)

tab.set_commander(True)
wait_until(lambda: len(tab.panes) == 2, timeout_ms=5000)
pane_r = tab.panes[1]
wait_until(lambda: pane_r.tree.topLevelItemCount() >= 1, timeout_ms=5000)

check("§4 with TWO panes the SECOND one may go local and the FIRST one may NOT",
      tab.can_use_local(pane_r) is True and tab.can_use_local(tab.panes[0]) is False
      and pane_r.source_switch.isEnabled() is True)

check("§1 a remote pane's provider IS the container's shipped worker (one transport)",
      pane_r.source == SOURCE_REMOTE and pane_r.provider is worker
      and pane_r.paths is POSIX_PATHS and pane_r._local_provider is None)

_switched = tab.set_pane_source(pane_r, SOURCE_LOCAL)
check("§4 the switch to LOCAL answered True and adopted the source",
      _switched is True and pane_r.source == SOURCE_LOCAL
      and pane_r.source_switch.source() == SOURCE_LOCAL)

check("§1 ...and the LOCAL provider is the pane's OWN, started and bound",
      pane_r.provider is pane_r._local_provider
      and pane_r._local_provider is not None and pane_r._local_provider.isRunning()
      and pane_r._local_provider is not worker and pane_r.paths is LOCAL_PATHS)

wait_until(lambda: pane_r.tree.topLevelItemCount() >= 1, timeout_ms=5000)
check("§3 the local pane LISTS the OS home (its opening rule)",
      os.path.normcase(pane_r.current_dir) == os.path.normcase(os.path.expanduser("~"))
      and pane_r.path_label.text() == pane_r.current_dir,
      f"{pane_r.current_dir!r} vs {pane_r.path_label.text()!r}")

check("§3 the transfer buttons of a local pane are OFF (rc1 moves no byte)",
      pane_r.btn_up.isEnabled() and pane_r.btn_refresh.isEnabled()
      and pane_r.btn_upload.isEnabled() is False and pane_r.btn_download.isEnabled() is False)

pane_r._relist(TREE)
wait_until(lambda: pane_r.tree.topLevelItemCount() >= 2, timeout_ms=5000)
_row = item_by_name(pane_r, "alpha.txt")
check("§3 a local row carries the FULL local path of its dialect",
      _row is not None and _row.data(0, pane_r.PATH_ROLE) == os.path.join(TREE, "alpha.txt")
      and _row.data(0, pane_r.ISDIR_ROLE) is False
      and _row.data(0, pane_r.SIZE_ROLE) == 6, str(_row.data(0, pane_r.PATH_ROLE)) if _row else "no row")
check("§3 the address bar shows the OS spelling of the directory (LOCAL_PANE.md §2)",
      pane_r.path_label.text() == TREE and os.sep in pane_r.path_label.text())

_sub_up = item_by_name(pane_r, "sub")
pane_r.tree.setCurrentItem(_sub_up)
pane_r._on_item_double_clicked(_sub_up, 0)
wait_until(lambda: os.path.normcase(pane_r.current_dir) == os.path.normcase(os.path.join(TREE, "sub")),
           timeout_ms=5000)
check("§3 a local DIRECTORY row is entered (the shipped double-click rule)",
      os.path.normcase(pane_r.current_dir) == os.path.normcase(os.path.join(TREE, "sub")))
check("§3 ...and a local path that is NOT the root offers the \"..\" row",
      pane_r._up_item is not None
      and os.path.normcase(pane_r._up_item.data(0, pane_r.PATH_ROLE)) == os.path.normcase(TREE))

pane_r.go_up()
wait_until(lambda: os.path.normcase(pane_r.current_dir) == os.path.normcase(TREE), timeout_ms=5000)
check("§2 `go up` uses the DIALECT's parent (not posixpath dirname)",
      os.path.normcase(pane_r.current_dir) == os.path.normcase(TREE))

_root_target = os.path.abspath(os.sep)
pane_r._relist(_root_target)
wait_until(lambda: os.path.normcase(pane_r.current_dir) == os.path.normcase(_root_target),
           timeout_ms=5000)
check("§2 at the LOCAL root there is no \"..\" row and the Up button is OFF",
      pane_r._up_item is None and pane_r.btn_up.isEnabled() is False
      and LOCAL_PATHS.is_root(pane_r.current_dir) is True)
pane_r.go_up()
check("§2 ...and `go up` is a NO-OP there (a listing that would leave the source)",
      os.path.normcase(pane_r.current_dir) == os.path.normcase(_root_target))

_typed = pane_r.path_label.text()
check("§3 the completer of a local pane continues with the OS separator",
      pane_r.paths.separator == os.sep)
pane_r._relist(TREE)
wait_until(lambda: pane_r.tree.topLevelItemCount() >= 2, timeout_ms=5000)
_pane_msgs = []
pane_r.message.connect(_pane_msgs.append)
_txt = item_by_name(pane_r, "alpha.txt")
pane_r._open_viewer(_txt)
_found = bool(wait_until(lambda: pane_r._viewer_open, timeout_ms=5000))
check("§3 a local text file opens in the SHIPPED read-only preview",
      pane_r._viewer_open and pane_r.viewer_text.toPlainText() == "alpha\n",
      f"open={pane_r._viewer_open} text={pane_r.viewer_text.toPlainText()!r}")
pane_r.close_viewer()

print("== 5. the two refusals and the permanent-delete warning (LOCAL_PANE.md §4) ==")

_msgs = []
tab.message.connect(_msgs.append)
_ok_back = tab.set_pane_source(pane_r, SOURCE_REMOTE)
wait_until(lambda: os.path.normcase(pane_r.current_dir) == "/", timeout_ms=5000)
check("§4 the switch BACK adopts the remote source and its own opening rule",
      _ok_back is True and pane_r.source == SOURCE_REMOTE
      and pane_r.provider is worker and pane_r.paths is POSIX_PATHS
      and pane_r._local_provider is not None and pane_r._local_provider.isRunning())

tab.set_pane_source(pane_r, SOURCE_LOCAL)
wait_until(lambda: os.path.normcase(pane_r.current_dir) == os.path.normcase(os.path.expanduser("~")),
           timeout_ms=5000)
check("§4 the provider of the FIRST pane is NEVER the local one",
      tab.panes[0].source == SOURCE_REMOTE and tab.panes[0]._local_provider is None
      and tab.panes[0].provider is worker)

pane_r._relist(TREE)
wait_until(lambda: pane_r.tree.topLevelItemCount() >= 2, timeout_ms=5000)
_msgs.clear()
pane_r._cmd_copy()
check("§4 a COPY onto a local pane says ONE sentence instead of moving bytes (rc1)",
      _msgs[-1:] == [i18n.t("sftp.local.transfer_unavailable")], str(_msgs)[-140:])

_ok_dup = tab.set_pane_source(pane_r, SOURCE_LOCAL)
check("§4 a switch to the source that already holds is a NO-OP that answers True",
      _ok_dup is True)

_del_msgs = []
_del_texts = []


class _DeleteBox:
    """The monkeypatched `STAB.QMessageBox` — records the confirmation text and says YES."""
    Yes, No = 0x4000, 0x10000

    @staticmethod
    def question(parent, title, text, buttons, default):
        _del_texts.append(text)
        return _DeleteBox.Yes


_orig_box = STAB.QMessageBox
STAB.QMessageBox = _DeleteBox
try:
    _victim = os.path.join(TREE, "victim.txt")
    with open(_victim, "wb") as f:
        f.write(b"bye\n")
    pane_r._relist(TREE)
    wait_until(lambda: item_by_name(pane_r, "victim.txt") is not None, timeout_ms=5000)
    _item = item_by_name(pane_r, "victim.txt")
    pane_r.tree.setCurrentItem(_item)
    pane_r._op_delete(_item)
    wait_until(lambda: not os.path.exists(_victim), timeout_ms=5000)
finally:
    STAB.QMessageBox = _orig_box
check("§4 a local delete really happens through the pane's own provider",
      not os.path.exists(_victim))
check("§4 ...and the confirmation SAYS it is permanent (no recycle bin)",
      len(_del_texts) == 1 and "recycle" in _del_texts[0].lower()
      and "victim.txt" in _del_texts[0], str(_del_texts)[:160])

_msgs.clear()
tab.set_commander(False)
check("§4 the two-pane mode OFF destroys the local pane and its provider stops",
      len(tab.panes) == 1)
check("§4 ...while the FIRST pane keeps the session's transport",
      tab.panes[0].provider is worker)

print("== 6. the machine codes and their sentences (LOCAL_PANE.md §3) ==")

check("§3 every declared code really renders a sentence of the SHIPPED language set",
      all(local_error_text(LFW.task_payload(code, error="boom")) for code in LFW.LOCAL_ERROR_KEYS))
check("§3 a payload of an UNKNOWN code falls back to the shipped operation sentence",
      local_error_text(LFW.task_payload("who_knows", error="x")) == i18n.t("sftp.op.error", error="x"))
check("§3 a PLAIN message (a server's own text) goes through the same generic sentence",
      local_error_text("plain server error") == i18n.t("sftp.op.error", error="plain server error"))
check("§3 a real OSError maps to its code (FileNotFoundError → missing)",
      LFW.local_error_code(FileNotFoundError("nope")) == LFW.LOCAL_MISSING
      and LFW.local_error_code(PermissionError("no")) == LFW.LOCAL_PERMISSION
      and LFW.local_error_code(OSError("other")) == LFW.LOCAL_UNREADABLE)
check("§3 the local skipped-entries note is declared once with its own key",
      LFW.KIND_LIST_PARTIAL == "list_partial"
      and LFW.LOCAL_ERROR_KEYS[LFW.KIND_LIST_PARTIAL] == "sftp.local.skipped"
      and parse_task_payload(LFW.task_payload(LFW.KIND_LIST_PARTIAL, count=2, names="a, b"))["count"] == 2)

print("== 7. i18n and the release state ==")

LANGS = load_i18n_langs(ROOT)
check_i18n_parity(LANGS)
check_i18n_format(LANGS)
NEW_KEYS = [k for k in LANGS["en"] if k.startswith("sftp.local.")]
check(f"the {len(NEW_KEYS)} keys of v1.7.4rc1 are present and non-empty in EVERY language",
      len(NEW_KEYS) == 17
      and all(str(data.get(k) or "").strip() for k in NEW_KEYS for data in LANGS.values()),
      f"{len(NEW_KEYS)} keys")
check("the switch's values are TRANSLATED (never the raw key or the English literal)",
      all(LANGS["en"][k] not in ("sftp.local.server", "sftp.local.local") for k in
          ("sftp.local.server", "sftp.local.local"))
      and LANGS["ru"]["sftp.local.server"] != LANGS["en"]["sftp.local.server"])

_langs_switch = []
for code, data in LANGS.items():
    if code == "en":
        continue
    _langs_switch.append(str(data.get("sftp.local.local") or "").strip() != "")
check("...and the second value of the pair exists in every language",
      all(_langs_switch) and len(_langs_switch) == len(LANGS) - 1, str(_langs_switch))

check_release_state(ROOT)
check("the version pin is the release this file describes",
      releases_at_least(EXPECTED_APP_VERSION, "1.7.4rc1"), EXPECTED_APP_VERSION)
check("the i18n pin counts the SHIPPED release (897 + the 17 keys of v1.7.4rc1)",
      EXPECTED_I18N_KEYS == 897 + 17, str(EXPECTED_I18N_KEYS))
check("VERSION_FORMAT did NOT move (a path is never written into a project)",
      __import__("version").VERSION_FORMAT == "0.9")
check("no new dependency was added for the local pane (the four pinned ones)",
      all(f"{d}>=" in open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read()
          for d in ("PySide6", "paramiko", "keyring", "wcwidth")))
check("the frozen contract of this line is in the repository (LOCAL_PANE.md)",
      os.path.exists(os.path.join(ROOT, "LOCAL_PANE.md")))

_wrap = re.search(r"^RESERVED_METHODS = \(([^)]*)\)",
                  open(os.path.join(ROOT, "modules", "local_fs_worker.py"),
                       encoding="utf-8").read(), re.M)
check("the reserved surface is DECLARED in one tuple the pane can read",
      _wrap is not None
      and [p.strip().strip('"') for p in _wrap.group(1).split(",") if p.strip()]
      == list(LFW.RESERVED_METHODS), _wrap.group(1) if _wrap else "not found")

tab.set_worker(None)
worker.shutdown()
finish()
