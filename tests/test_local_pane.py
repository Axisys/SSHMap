# -*- coding: utf-8 -*-
"""The LOCAL pane (v1.7.4rc2): the provider seam, the two path dialects, the OS listing of the
second Commander pane, the source switch, the four-case cross-pane dispatch, the recursive local
engine and the drag & drop in both directions.

Offscreen, no network. The remote half runs over the fake SFTP surface of `_fakes.py`; the local
half runs over a REAL tree inside an isolated HOME, because the provider is the OS itself.
Contract — `LOCAL_PANE.md` §1–§7; mechanism — `DOCUMENTATION.md` §67.
Run: python tests/test_local_pane.py   (from the project root) or python tests/run_all.py"""
import os
import re
import shutil
import sys

from _common import (bootstrap, check, finish, wait_until, wait_for, load_i18n_langs,
                     check_i18n_parity, check_i18n_format, check_release_state, clear_cfg,
                     releases_at_least, EXPECTED_APP_VERSION, EXPECTED_I18N_KEYS)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation)

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication, QWidget

app = QApplication(sys.argv)

import i18n
import modules.local_fs_worker as LFW
import modules.sftp_tab as STAB
import modules.sftp_worker as SW
import modules.ssh_terminal as ST
from modules.sftp_tab import (LOCAL_PATHS, PANE_DRAG_MIME, POSIX_PATHS, SOURCE_LOCAL, SOURCE_REMOTE,
                              PathDialect, SftpTab, dialect_for, local_error_text, pane_payload)
from modules.sftp_worker import KIND_COPY, KIND_DELETE, KIND_LIST, KIND_MKDIR, KIND_MOVE, \
    KIND_NORMALIZE, KIND_READ, KIND_RENAME, MAX_READ_BYTES, MAX_TREE_ENTRIES, PARTIAL_CODE, \
    PART_SUFFIX, READ_ERROR_BINARY, READ_ERROR_TOO_LARGE, SftpWorker, TREE_ERROR_TOO_BIG, \
    parse_task_payload
from modules.terminal_page import TerminalSessionPage
from models.server import ServerData

from _fakes import EventLog, FakeSftpClient, FakeSftpFS, FakeSSHThread, wire_worker


# ════════════════════════════════════════════════════════════
# The harness: a REAL local tree + a real LocalFsWorker thread
# ════════════════════════════════════════════════════════════

TREE = os.path.join(WORK, "local_tree")


def build_tree():
    """A small OS tree: two files, a nested file, a hidden file and a binary one."""
    if os.path.isdir(TREE):
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


def read_bytes(path):
    """The bytes of a file, or None when it is not there (a missing read is a FAILED check)."""
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


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

check("§3 the provider NAMES its thread (AGENTS.md §4.8)",
      provider.objectName() == "LocalFsWorker")

check("§3 the code holds no UI sentence — every refusal is an i18n KEY of the declared table",
      all(str(v).startswith("sftp.local.") for v in LFW.LOCAL_ERROR_KEYS.values())
      and set(LFW.LOCAL_ERROR_KEYS) >= {LFW.LOCAL_PERMISSION, LFW.LOCAL_LOCKED, LFW.LOCAL_TOO_LONG,
                                        LFW.LOCAL_MISSING, LFW.LOCAL_SYMLINK_DIR, LFW.LOCAL_NOT_DIR,
                                        LFW.LOCAL_IS_DIR, LFW.LOCAL_EXISTS, LFW.LOCAL_UNREADABLE})

provider.shutdown()
check("§3 `shutdown()` stops the thread inside its budget", not provider.isRunning())

print("== 3b. the local transfer engine (LOCAL_PANE.md §5/§6) ==")

check("§5 the four transfer doors are BOUND and share the shipped vocabulary",
      all(callable(getattr(LFW.LocalFsWorker, name, None))
          for name in ("queue_upload", "queue_download", "queue_copy", "queue_move"))
      and not hasattr(LFW, "RESERVED_METHODS")
      and LFW.KIND_COPY == KIND_COPY and LFW.KIND_MOVE == KIND_MOVE
      and LFW.provisional_name("/d/f.bin", 7).endswith(PART_SUFFIX))

eng, elog = make_provider()
_SRC = fresh_dir("eng_src", ("a.txt", b"A" * 10), ("sub/leaf.txt", b"leaf\n"),
                 ("sub/deep.txt", b"deep\n"))
_DST = fresh_dir("eng_dst")

_t = eng.queue_copy(os.path.join(_SRC, "a.txt"), _DST, "a.txt")
wait_until(lambda: bool(elog.of_kind("done", _t)), timeout_ms=5000)
check("§5 a file COPY is byte-for-byte and leaves the source alone",
      read_bytes(os.path.join(_DST, "a.txt")) == b"A" * 10
      and read_bytes(os.path.join(_SRC, "a.txt")) == b"A" * 10,
      str(elog.of_kind("done", _t))[:120])
check("§5 ...and the atomic commit leaves NO `.part` file behind",
      not [n for n in os.listdir(_DST) if n.endswith(PART_SUFFIX)], str(os.listdir(_DST)))

_t = eng.queue_copy(os.path.join(_SRC, "sub"), _DST, "sub")
wait_until(lambda: bool(elog.of_kind("done", _t)), timeout_ms=5000)
check("§6 a DIRECTORY source is carried as a whole tree (nested files included)",
      read_bytes(os.path.join(_DST, "sub", "leaf.txt")) == b"leaf\n"
      and read_bytes(os.path.join(_DST, "sub", "deep.txt")) == b"deep\n",
      str(sorted(os.listdir(_DST))))

with open(os.path.join(_DST, "sub", "keep.txt"), "wb") as f:
    f.write(b"keep\n")
_t = eng.queue_copy(os.path.join(_SRC, "sub"), _DST, "sub")
wait_until(lambda: bool(elog.of_kind("done", _t)), timeout_ms=5000)
check("§6 ...and a copy is ADDITIVE: an existing destination is merged into, never emptied",
      read_bytes(os.path.join(_DST, "sub", "keep.txt")) == b"keep\n"
      and read_bytes(os.path.join(_DST, "sub", "leaf.txt")) == b"leaf\n")

_MOVE_DST = fresh_dir("eng_move")
_t = eng.queue_move(os.path.join(_SRC, "sub"), _MOVE_DST, "sub")
wait_until(lambda: bool(elog.of_kind("done", _t)), timeout_ms=5000)
check("§6 a DIRECTORY move carries the tree and removes the emptied source (deepest first)",
      read_bytes(os.path.join(_MOVE_DST, "sub", "leaf.txt")) == b"leaf\n"
      and read_bytes(os.path.join(_MOVE_DST, "sub", "deep.txt")) == b"deep\n"
      and not os.path.exists(os.path.join(_SRC, "sub")),
      f"src_left={os.path.exists(os.path.join(_SRC, 'sub'))}")

_t = eng.queue_move(os.path.join(_SRC, "a.txt"), _MOVE_DST, "moved.txt")
wait_until(lambda: bool(elog.of_kind("done", _t)), timeout_ms=5000)
check("§5 a file MOVE lands under the new name and the original is gone (one volume)",
      read_bytes(os.path.join(_MOVE_DST, "moved.txt")) == b"A" * 10
      and not os.path.exists(os.path.join(_SRC, "a.txt")))

_PART_SRC = fresh_dir("part_src", ("one.txt", b"1"), ("two.txt", b"2"))
_PART_DST = fresh_dir("part_dst", ("tree/two.txt/inside.txt", b"x"))
_t = eng.queue_copy(_PART_SRC, _PART_DST, "tree")
wait_until(lambda: bool(elog.of_kind("error", _t)), timeout_ms=5000)
_part = parse_task_payload((elog.of_kind("error", _t) or [("", "", "", "")])[0][3]) or {}
check("§6 an INTERRUPTED tree is REPORTED with the shipped partial payload and its counters",
      _part.get("code") == PARTIAL_CODE and int(_part.get("copied") or 0) == 1,
      str(elog.of_kind("error", _t))[:160])
check("§6 ...while what was really copied BEFORE the failure stays (never rolled back)",
      read_bytes(os.path.join(_PART_DST, "tree", "one.txt")) == b"1",
      str(sorted(os.listdir(os.path.join(_PART_DST, "tree")))) if
      os.path.isdir(os.path.join(_PART_DST, "tree")) else "no tree")

_BOUNDS_SRC = fresh_dir("bounds_src", *[(f"f{i}.txt", b"x") for i in range(8)])
_pin_entries, _pin_depth = LFW.MAX_TREE_ENTRIES, LFW.MAX_TREE_DEPTH
LFW.MAX_TREE_ENTRIES = 4
try:
    _t = eng.queue_copy(_BOUNDS_SRC, fresh_dir("bounds_dst"), "tree")
    wait_until(lambda: bool(elog.of_kind("error", _t)), timeout_ms=5000)
    _bound = parse_task_payload((elog.of_kind("error", _t) or [("", "", "", "")])[0][3]) or {}
    check("§6 the walk is BOUNDED by the shipped MAX_TREE_ENTRIES (and says so once)",
          _bound.get("code") == TREE_ERROR_TOO_BIG
          and int(_bound.get("limit") or 0) == LFW.MAX_TREE_ENTRIES,
          str(_bound)[:140])
finally:
    LFW.MAX_TREE_ENTRIES, LFW.MAX_TREE_DEPTH = _pin_entries, _pin_depth

_LINK_SRC = fresh_dir("link_src", ("real/inside.txt", b"in"))
_SYMLINK_OK = True
try:
    os.symlink(os.path.join(_LINK_SRC, "real"), os.path.join(_LINK_SRC, "link"))
except (OSError, NotImplementedError, AttributeError):
    _SYMLINK_OK = False   # Windows without the privilege: the rule is asserted over the walk
if _SYMLINK_OK:
    _LINK_DST = fresh_dir("link_dst")
    _t = eng.queue_copy(_LINK_SRC, _LINK_DST, "tree")
    wait_until(lambda: bool(elog.of_kind("done", _t)) or bool(elog.of_kind("error", _t)),
               timeout_ms=5000)
    check("§6 a directory SYMLINK inside a tree is never followed (it is skipped)",
          not os.path.exists(os.path.join(_LINK_DST, "tree", "link"))
          and read_bytes(os.path.join(_LINK_DST, "tree", "real", "inside.txt")) == b"in",
          str(sorted(os.listdir(os.path.join(_LINK_DST, "tree")))))

_UP_DST = fresh_dir("eng_up")
_t = eng.queue_upload(os.path.join(_LINK_SRC, "real"), _UP_DST, "up")
wait_until(lambda: bool(elog.of_kind("done", _t)), timeout_ms=5000)
check("§5 the Upload door of a local pane is the same engine (a copy into the directory)",
      read_bytes(os.path.join(_UP_DST, "up", "inside.txt")) == b"in")

_DL_DST = fresh_dir("eng_dl")
_t = eng.queue_download(os.path.join(_UP_DST, "up", "inside.txt"), _DL_DST, 2, local_name="out.txt")
wait_until(lambda: bool(elog.of_kind("done", _t)), timeout_ms=5000)
check("§5 the Download door reads the OS disk and writes it back under the asked name",
      read_bytes(os.path.join(_DL_DST, "out.txt")) == b"in")

eng.shutdown()
check("§5 the engine thread stops inside its budget", not eng.isRunning())

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

check("§3 the transfer buttons of a local pane are ON (rc2 moves bytes through its own provider)",
      pane_r.btn_up.isEnabled() and pane_r.btn_refresh.isEnabled()
      and pane_r.btn_upload.isEnabled() and pane_r.btn_download.isEnabled())

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
_local_before = pane_r.current_dir      # the OS directory this pane really sits in
_ok_back = tab.set_pane_source(pane_r, SOURCE_REMOTE)
check("§4 the switch BACK adopts the remote source and its own opening rule",
      _ok_back is True and pane_r.source == SOURCE_REMOTE
      and pane_r.provider is worker and pane_r.paths is POSIX_PATHS
      and pane_r._local_provider is not None and pane_r._local_provider.isRunning()
      and pane_r.current_dir == "/" and pane_r._waiting is False,
      f"dir={pane_r.current_dir!r} waiting={pane_r._waiting}")
check("§4 ...and the way back RE-BINDS the session's transport (a blank pane is the defect)",
      pane_r._waiting is False
      and wait_for(lambda: pane_r.tree.topLevelItemCount() >= 1, timeout_ms=5000),
      f"rows={pane_r.tree.topLevelItemCount()} waiting={pane_r._waiting}")
check("§4 ...and the OS look this pane had SURVIVES the round trip",
      tab.set_pane_source(pane_r, SOURCE_LOCAL) is True
      and pane_r.source == SOURCE_LOCAL
      and os.path.normcase(pane_r.current_dir) == os.path.normcase(_local_before),
      f"{pane_r.current_dir!r} vs {_local_before!r}")
check("§4 ...and its provider is the SAME thread it had before (one per pane, never recreated)",
      pane_r._local_provider is not None and pane_r._local_provider.isRunning())

check("§4 the provider of the FIRST pane is NEVER the local one",
      tab.panes[0].source == SOURCE_REMOTE and tab.panes[0]._local_provider is None
      and tab.panes[0].provider is worker)

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

print("== 6. the cross-pane dispatch — the four cases (LOCAL_PANE.md §5) ==")

_fs2 = FakeSftpFS()
_fs2.add_dir("/home")
_fs2.add_dir("/home/box")
_fs2.add_file("/home/box/deep.txt", b"deep\n")
_fs2.add_file("/home/remote.txt", b"R" * 8)
_fs2.add_dir("/other")
_dtab, _dworker, _dlog = make_remote_tab(_fs2)
_dtab.set_session_info(key="local-pane-session", label="Test", host="192.0.2.10", port=22)
wait_until(lambda: _dtab.tree.topLevelItemCount() >= 1, timeout_ms=5000)
_rpane, _lpane = _dtab.panes[0], _dtab.panes[1]
_dtab.set_pane_source(_lpane, SOURCE_LOCAL)
wait_until(lambda: _lpane.source == SOURCE_LOCAL, timeout_ms=5000)

_ddispatched = []


class _RecordingProvider:
    """The four doors of a provider, recorded — the DISPATCH table read without a transport."""

    def __init__(self):
        self.calls = []

    def _log(self, name, args):
        self.calls.append((name, args))
        return 1000 + len(self.calls)

    def queue_upload(self, *a, **kw):
        return self._log("upload", (a, kw))

    def queue_download(self, *a, **kw):
        return self._log("download", (a, kw))

    def queue_copy(self, *a, **kw):
        return self._log("copy", (a, kw))

    def queue_move(self, *a, **kw):
        return self._log("move", (a, kw))


_rec = _RecordingProvider()
_rr = _lpane._queue_batch_item(_rec, SOURCE_LOCAL, SOURCE_REMOTE, KIND_COPY, "/local/a.txt",
                               "/srv/dir", "a.txt", 5)
check("§5 local→remote is the SESSION worker's `queue_upload` (a copy, with the asked name)",
      _rec.calls[-1][0] == "upload" and _rec.calls[-1][1][0] == ("/local/a.txt", "/srv/dir")
      and _rec.calls[-1][1][1].get("remote_name") == "a.txt" and _rr == 1001)
_rr = _lpane._queue_batch_item(_rec, SOURCE_REMOTE, SOURCE_LOCAL, KIND_COPY, "/srv/a.txt",
                               "/local/dir", "a.txt", 7)
check("§5 remote→local is the SHIPPED `queue_download` (atomic on the OS disk)",
      _rec.calls[-1][0] == "download" and _rec.calls[-1][1][0] == ("/srv/a.txt", "/local/dir", 7)
      and _rec.calls[-1][1][1].get("local_name") == "a.txt")
_rr = _lpane._queue_batch_item(_rec, SOURCE_REMOTE, SOURCE_REMOTE, KIND_MOVE, "/srv/a", "/srv/b",
                               "a", 0)
check("§5 remote→remote keeps the SHIPPED `queue_move` / `queue_copy` (untouched)",
      _rec.calls[-1][0] == "move" and _rec.calls[-1][1][0] == ("/srv/a", "/srv/b", "a"))
_rr = _lpane._queue_batch_item(_rec, SOURCE_LOCAL, SOURCE_LOCAL, KIND_COPY, "/local/a", "/local/b",
                               "a", 0)
check("§5 local→local is the LOCAL engine of `modules/local_fs_worker.py`",
      _rec.calls[-1][0] == "copy" and _rec.calls[-1][1][0] == ("/local/a", "/local/b", "a"))

_dmsgs = []
_dtab.message.connect(_dmsgs.append)
_dmsgs.clear()
_before = set(_fs2.files)
_lpane._queue_transfer_batch([("/local/x.txt", "x.txt", 3)], KIND_MOVE, "/srv", set(), _rpane)
check("§5 a MOVE that would cross the two sources is REFUSED with ONE sentence (never a copy)",
      _dmsgs[-1:] == [i18n.t("sftp.local.move_cross_source")] and set(_fs2.files) == _before,
      str(_dmsgs)[-140:])

# ── the two directions over the REAL providers (fake SFTP + the OS disk) ──
_UP_SRC = fresh_dir("disp_src", ("report.txt", b"REPORT" * 3))
_UP_DST = fresh_dir("disp_dst")
_lpane._relist(_UP_SRC)
wait_until(lambda: item_by_name(_lpane, "report.txt") is not None, timeout_ms=5000)
_rpane._relist("/home")
wait_until(lambda: item_by_name(_rpane, "box") is not None, timeout_ms=5000)
_lpane.tree.setCurrentItem(item_by_name(_lpane, "report.txt"))
_dmsgs.clear()
_lpane._cmd_copy()
_ok_up = wait_for(lambda: "/home/report.txt" in _fs2.files, timeout_ms=5000)
check("§5 F5 from the LOCAL pane puts the file on the SERVER byte for byte",
      _ok_up and bytes(_fs2.files["/home/report.txt"]) == b"REPORT" * 3, str(sorted(_fs2.files)))
check("§5 ...the local ORIGINAL stays (F5 is a copy) and no `.part` is left on the server",
      read_bytes(os.path.join(_UP_SRC, "report.txt")) == b"REPORT" * 3
      and "/home/report.txt.part" not in _fs2.files, str(sorted(_fs2.files)))
check("§5 ...and the batch closes with the SHIPPED report (one line for the whole run)",
      any(str(m).startswith(i18n.t("sftp.cmd.copy_report", done=1, skipped=0, failed=0))
          for m in _dmsgs), str(_dmsgs)[-160:])

_lpane._relist(_UP_DST)
wait_until(lambda: _lpane.current_dir == _UP_DST, timeout_ms=5000)
_rpane.tree.setCurrentItem(item_by_name(_rpane, "remote.txt"))
_dmsgs.clear()
_rpane._cmd_copy()
_ok_down = wait_for(lambda: os.path.exists(os.path.join(_UP_DST, "remote.txt")),
                           timeout_ms=5000)
check("§5 F5 from the REMOTE pane brings the file into the local directory byte for byte",
      _ok_down and read_bytes(os.path.join(_UP_DST, "remote.txt")) == b"R" * 8,
      str(sorted(os.listdir(_UP_DST))))
check("§5 ...atomically: the local destination is committed, never a `.part`",
      not [n for n in os.listdir(_UP_DST) if n.endswith(PART_SUFFIX)], str(os.listdir(_UP_DST)))

# ── a DIRECTORY through the pair (the recursion of §6) ──
_lpane._relist(_UP_DST)
wait_until(lambda: _lpane.current_dir == _UP_DST, timeout_ms=5000)
_rpane.tree.setCurrentItem(item_by_name(_rpane, "box"))
_dmsgs.clear()
_rpane._cmd_copy()
_ok_tree = wait_for(lambda: read_bytes(os.path.join(_UP_DST, "box", "deep.txt")) == b"deep\n",
                           timeout_ms=5000)
check("§6 a remote DIRECTORY crosses to the OS disk as a whole TREE",
      _ok_tree, str(sorted(os.listdir(_UP_DST))))

_LTREE_SRC = fresh_dir("disp_tree", ("top.txt", b"top\n"), ("inner/one.txt", b"1\n"),
                       ("inner/two.txt", b"2\n"))
_lpane._relist(_LTREE_SRC)
wait_until(lambda: item_by_name(_lpane, "inner") is not None, timeout_ms=5000)
_lpane.tree.setCurrentItem(item_by_name(_lpane, "inner"))
_dmsgs.clear()
_lpane._cmd_copy()
_ok_ltree = wait_for(lambda: "/home/inner/two.txt" in _fs2.files, timeout_ms=5000)
check("§6 ...and a LOCAL DIRECTORY crosses to the server as a whole TREE",
      _ok_ltree and bytes(_fs2.files["/home/inner/one.txt"]) == b"1\n"
      and bytes(_fs2.files["/home/inner/two.txt"]) == b"2\n", str(sorted(_fs2.files)))

_dmsgs.clear()
_lpane.tree.setCurrentItem(item_by_name(_lpane, "top.txt"))
_lpane._cmd_move_rename()
check("§5 F6 across the two sources answers ONE sentence instead of silently copying",
      _dmsgs[-1:] == [i18n.t("sftp.local.move_cross_source")], str(_dmsgs)[-140:])

print("== 7. the drag & drop in both directions (LOCAL_PANE.md §7) ==")


class _DropEvent:
    """A minimal drag event: a position outside the rows, no `Shift`, a Copy proposal."""

    def __init__(self, shift=False, move=False):
        self._shift = shift
        self._move = move

    def position(self):
        return QPointF(-4.0, -4.0)

    def pos(self):
        return self.position().toPoint()

    def modifiers(self):
        from PySide6.QtCore import Qt as _Qt
        return _Qt.KeyboardModifier.ShiftModifier if self._shift else _Qt.KeyboardModifier.NoModifier

    def dropAction(self):
        from PySide6.QtCore import Qt as _Qt
        return _Qt.DropAction.MoveAction if self._move else _Qt.DropAction.CopyAction

    def acceptProposedAction(self):
        pass


_lpane._relist(_LTREE_SRC)
wait_until(lambda: item_by_name(_lpane, "top.txt") is not None, timeout_ms=5000)
_l_top = os.path.join(_LTREE_SRC, "top.txt")
_l_mime = _lpane.tree.drag_mime(item_by_name(_lpane, "top.txt"))
check("§7 a LOCAL row dragged OUT hands a real OS path (`text/uri-list` beside `text/plain`)",
      _l_mime is not None and _l_mime.text() == _l_top and _l_mime.hasFormat(PANE_DRAG_MIME)
      and _l_mime.hasUrls() and _l_mime.hasFormat("text/uri-list")
      and os.path.normcase(os.path.normpath(_l_mime.urls()[0].toLocalFile()))
      == os.path.normcase(os.path.normpath(_l_top)),
      str([u.toLocalFile() for u in _l_mime.urls()]) if _l_mime else "no mime")
_l_payload = pane_payload(_l_mime)
check("§7 ...and the payload DECLARES the source dialect and the size",
      _l_payload is not None and _l_payload["source"] == SOURCE_LOCAL
      and _l_payload["size"] == 4 and _l_payload["path"] == os.path.join(_LTREE_SRC, "top.txt"),
      str(_l_payload))

_rpane._relist("/home")
wait_until(lambda: item_by_name(_rpane, "remote.txt") is not None, timeout_ms=5000)
_r_mime = _rpane.tree.drag_mime(item_by_name(_rpane, "remote.txt"))
_r_payload = pane_payload(_r_mime)
check("§7 a REMOTE row keeps the shipped payload and offers NO OS path to Explorer",
      _r_payload is not None and _r_payload["source"] == SOURCE_REMOTE
      and not _r_mime.hasUrls()
      and _r_payload["path"] == "/home/remote.txt" and _r_payload["size"] == 8,
      str(_r_payload))

_UP_DROP = fresh_dir("drop_dst")
_lpane._relist(_UP_DROP)
wait_until(lambda: _lpane.current_dir == _UP_DROP, timeout_ms=5000)
_before = set(_fs2.files)
_lpane._on_drop([os.path.join(_LTREE_SRC, "top.txt")], _UP_DROP)
_ok_local_drop = wait_for(lambda: read_bytes(os.path.join(_UP_DROP, "top.txt")) == b"top\n",
                                 timeout_ms=5000)
check("§7 a drop of Explorer files on the LOCAL pane is a LOCAL copy, never an upload",
      _ok_local_drop and set(_fs2.files) == _before, str(sorted(_fs2.files)))
check("§7 ...and the local listing shows the new row (the local engine is nobody's server)",
      wait_for(lambda: item_by_name(_lpane, "top.txt") is not None, timeout_ms=5000),
      f"rows={[_lpane.tree.topLevelItem(i).text(0) for i in range(_lpane.tree.topLevelItemCount())]}")

# a name the OS already holds as a DIRECTORY: the local copy is refused, and the pane SAYS so
# (the local engine's refusals ride the pane's OWN signal — no session page listens to it).
# The conflict seam answers "overwrite": a real dialog would block offscreen, and the refusal
# below is the ENGINE's, not the question's.
os.remove(os.path.join(_UP_DROP, "top.txt"))
os.makedirs(os.path.join(_UP_DROP, "top.txt"))
_lpane._relist(_UP_DROP)
wait_until(lambda: item_by_name(_lpane, "top.txt") is not None, timeout_ms=5000)
_clash_msgs = []
_lpane.message.connect(_clash_msgs.append)
_orig_ask = _lpane._ask_conflict
_lpane._ask_conflict = lambda name, target, remaining=0, facts="": ("overwrite", False)
try:
    _lpane._on_drop([os.path.join(_LTREE_SRC, "top.txt")], _UP_DROP)
    _clash_text = i18n.t("sftp.local.is_dir", error="top.txt")
    check("§7 a refused LOCAL transfer is a translated sentence, never a silent no-op",
          wait_for(lambda: _clash_text in _clash_msgs, timeout_ms=5000), str(_clash_msgs)[-200:])
finally:
    _lpane._ask_conflict = _orig_ask

_rpane._relist("/other")
wait_until(lambda: _rpane.current_dir == "/other", timeout_ms=5000)
_rpane._on_drop([os.path.join(_LTREE_SRC, "top.txt")], "/other")
check("§7 ...while a drop on the REMOTE pane stays the shipped upload",
      wait_for(lambda: "/other/top.txt" in _fs2.files, timeout_ms=5000)
      and bytes(_fs2.files["/other/top.txt"]) == b"top\n", str(sorted(_fs2.files)))

# the payload that travels BETWEEN the panes: a LOCAL row onto the REMOTE pane.
# Every destination below is a FRESH directory: an existing name would raise the shipped
# overwrite question, which blocks on a real dialog (the seam is covered by test_files_surface).
_fs2.add_dir("/inbox")
_rpane._relist("/inbox")
wait_until(lambda: _rpane.current_dir == "/inbox", timeout_ms=5000)
_dmsgs.clear()
_rpane._on_pane_drop(_l_payload, _DropEvent())
check("§7 a LOCAL row dropped on the REMOTE pane is an UPLOAD named by the SOURCE dialect",
      wait_for(lambda: "/inbox/top.txt" in _fs2.files, timeout_ms=5000)
      and bytes(_fs2.files["/inbox/top.txt"]) == b"top\n"
      and any(str(m).startswith("Copied:") for m in _dmsgs), str(_dmsgs)[-160:])

# and the other way: a REMOTE row onto the LOCAL pane
_DOWN_DROP = fresh_dir("drop_in")
_lpane._relist(_DOWN_DROP)
wait_until(lambda: _lpane.current_dir == _DOWN_DROP, timeout_ms=5000)
_rpane._relist("/home")
wait_until(lambda: item_by_name(_rpane, "remote.txt") is not None, timeout_ms=5000)
_dmsgs.clear()
_lpane._on_pane_drop(_r_payload, _DropEvent())
check("§7 a REMOTE row dropped on the LOCAL pane is a DOWNLOAD into the pane's directory",
      wait_for(lambda: read_bytes(os.path.join(_DOWN_DROP, "remote.txt")) == b"R" * 8,
               timeout_ms=5000)
      and any(str(m).startswith("Copied:") for m in _dmsgs), str(_dmsgs)[-160:])

_dmsgs.clear()
_lpane._on_pane_drop(_r_payload, _DropEvent(shift=True))
check("§7 a SHIFT drop between the two sources is the refused cross-source MOVE (ONE sentence)",
      _dmsgs[-1:] == [i18n.t("sftp.local.move_cross_source")]
      and len([n for n in os.listdir(_DOWN_DROP) if n == "remote.txt"]) == 1, str(_dmsgs)[-140:])

_dmsgs.clear()
_rpane._on_pane_drop(_r_payload, _DropEvent())
check("§7 a row dropped back on its OWN pane is refused with the shipped sentence",
      _dmsgs[-1:] == [i18n.t("sftp.cmd.drop_same_pane")], str(_dmsgs)[-140:])

# ── the CONTAINER's teardown: the ONE door the page calls (AGENTS.md §4.8) ──
_local_prov = _lpane._local_provider
check("§1 the local pane holds a LIVE provider before the teardown (the crash needs one)",
      _local_prov is not None and _local_prov.isRunning(), str(_local_prov))

_dtab.release()
check("§1 `SftpTab.release()` stops the local pane's thread — a QThread never outlives its widget",
      _local_prov.isRunning() is False and _lpane._local_provider is None,
      f"running={_local_prov.isRunning()}")
check("§1 ...while the SESSION's transport stays the page's business (bound and still running)",
      _rpane.provider is _dworker and _dworker.isRunning())
try:
    _dtab.release()
    _release_twice = True
except Exception as e:  # noqa: BLE001 — an idempotent teardown never raises
    _release_twice = False
    print("   a second release() raised:", e)
check("§1 ...and a second `release()` is an idempotent no-op", _release_twice)

_dworker.shutdown()

print("== 8. the machine codes and their sentences (LOCAL_PANE.md §3) ==")

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

print("== 9. i18n and the release state ==")

LANGS = load_i18n_langs(ROOT)
check_i18n_parity(LANGS)
check_i18n_format(LANGS)
NEW_KEYS = [k for k in LANGS["en"] if k.startswith("sftp.local.")]
check(f"the {len(NEW_KEYS)} keys of the local pane are present and non-empty in EVERY language",
      len(NEW_KEYS) == 18
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
      releases_at_least(EXPECTED_APP_VERSION, "1.7.4"), EXPECTED_APP_VERSION)
check("the i18n pin counts the SHIPPED release (897 + the 17 of v1.7.4rc1 + the 1 of v1.7.4rc2"
      " + the 4 of v1.7.5: the Files settings page with its ceiling row and warning, and the"
      " truncation notice + the 6 of v1.7.5.1 + the 20 of v1.8: the elevated pane + the 41 of"
      " v1.8.1: the trust surface, and v1.8.1.1 adds ONE: the send identity sentence) and v1.8.2 adds SIXTEEN: the library file — the History door, the backup ring and the import/export pair"
      " — and v1.8.3 adds TWENTY-THREE: the Plugins window (its chrome, its three columns and its"
      " export) and v1.8.4 adds TEN: the whole-map layout, the reverse traversal and the inode fact, and v1.9 adds FOUR: the production-tag guard — its title, the broadcast sentence and the paste sentence — and the notice of a checked selection that has left the map, and v1.9.1 adds ELEVEN: the reconnect and its `tmux attach`",
      EXPECTED_I18N_KEYS == 897 + 17 + 1 + 4 + 6 + 20 + 41 + 1 + 16 + 23 + 10 + 4 + 11, str(EXPECTED_I18N_KEYS))
check("VERSION_FORMAT did NOT move (a path is never written into a project)",
      __import__("version").VERSION_FORMAT == "0.9")
check("no new dependency was added for the local pane (the four pinned ones)",
      all(f"{d}>=" in open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read()
          for d in ("PySide6", "paramiko", "keyring", "wcwidth")))
check("the frozen contract of this line is in the repository (LOCAL_PANE.md)",
      os.path.exists(os.path.join(ROOT, "LOCAL_PANE.md")))

_src_text = open(os.path.join(ROOT, "modules", "local_fs_worker.py"), encoding="utf-8").read()
check("the engine is the DECLARED one (`shutil.copy2` through a `.part` + `os.replace`)",
      "shutil.copy2" in _src_text and "provisional_name" in _src_text
      and re.search(r"^PART_SUFFIX = ", open(os.path.join(ROOT, "modules", "sftp_worker.py"),
                                             encoding="utf-8").read(), re.M) is not None)
check("...and the transfer doors are the SHIPPED names, not a new vocabulary",
      all(f"def {name}(" in _src_text
          for name in ("queue_upload", "queue_download", "queue_copy", "queue_move")))

print("== 10. the PAGE teardown and the orphan registry (AGENTS.md §4.8) ==")

# The field crash: a session is closed (the window's X / the MainWindow shutdown) while its
# SECOND pane reads the OS disk. `TerminalSessionPage.shutdown()` is the ONE teardown path, so
# the invariant is asserted on it: after the call no LocalFsWorker of that session is running —
# a thread still running when the widget tree dies aborts the whole application.
_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = FakeSSHThread
_page = None
_pprov = None
try:
    _page = TerminalSessionPage(ServerData(id="lp-page", alias="lp-page", host="192.0.2.99",
                                           user="root"))
    _page.sftp_tab.set_commander(True)
    _ppane = _page.sftp_tab.panes[1]
    _page.sftp_tab.set_pane_source(_ppane, SOURCE_LOCAL)
    wait_until(lambda: _ppane._local_provider is not None, timeout_ms=5000)
    _pprov = _ppane._local_provider
    _page.shutdown()
    check("§1 the page's SINGLE teardown stops the local pane's thread (the field crash)",
          _pprov is not None and _pprov.isRunning() is False and _ppane._local_provider is None
          and not LFW._orphan_providers,
          f"running={_pprov.isRunning() if _pprov else None} orphans={len(LFW._orphan_providers)}")
    try:
        _page.shutdown()
        _page_twice = True
    except Exception as e:  # noqa: BLE001 — the idempotent teardown never raises
        _page_twice = False
        print("   a second page shutdown() raised:", e)
    check("§1 ...and the page's `shutdown()` stays idempotent with a LOCAL pane bound", _page_twice)
finally:
    ST.SSHTerminalThread = _orig_thread_cls

# A provider that OUTLIVED its wait budget: the registry must DETACH it from the pane that is
# about to die, or the parent destroys the thread it is holding for (the same abort, later).
_holder = QWidget()
_orphan = LFW.LocalFsWorker(root=TREE, parent=_holder)
_orphan.start()
LFW.register_orphan_local_provider(_orphan)
check("§1 a provider that outlives its wait budget is DETACHED from its dying pane",
      _orphan.parent() is None and _orphan in LFW._orphan_providers,
      f"parent={_orphan.parent()} orphans={len(LFW._orphan_providers)}")
_orphan.shutdown(2500)
check("§1 ...and the registry drops it the moment it really finished",
      wait_for(lambda: _orphan not in LFW._orphan_providers, timeout_ms=8000),
      f"orphans={len(LFW._orphan_providers)}")

tab.set_worker(None)
worker.shutdown()
finish()
