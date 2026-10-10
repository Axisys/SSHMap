# -*- coding: utf-8 -*-
"""The Files surface's first follow-up (v1.7.5): the listing that SORTS, the preview the user SIZES
and the pane's SOURCE HEADER LINE.

§1 the column headers of a pane are real SORT KEYS (a row subclass over the ROLES, with the ".." row
pinned and the directories grouped above the files, in BOTH directions and over BOTH sources);
§2 the preview ceiling is a SETTING that TRUNCATES the read instead of refusing the file; §3 every
pane names its SOURCE in a header line (`LOCAL_PANE.md` §3). Offscreen and hermetic: the remote half
runs over `_fakes.py`, the local half over a real HOME tree. Mechanism — `DOCUMENTATION.md` §64."""
import inspect
import os
import shutil
import sys

from _common import (bootstrap, check, finish, wait_until, wait_for, clear_cfg, read_cfg,
                     load_i18n_langs, check_i18n_parity, check_i18n_format, check_release_state,
                     pane_family_files, pane_family_text, pane_func_body, pane_func_owner,
                     EXPECTED_APP_VERSION, EXPECTED_I18N_KEYS, releases_at_least)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation)

from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

import i18n
import modules.local_fs_worker as LFW
import modules.sftp_tab as STAB
import modules.sftp_worker as SW
from modules.sftp_pane_listing import ACTIVE_PANE_MARK
from modules.sftp_tab import (SOURCE_LOCAL, SftpTab, _SftpRowItem, clamp_viewer_max_bytes,
                              format_size, preview_block_reason, resolve_viewer_max_bytes,
                              row_name, row_path, save_viewer_max_bytes)
from modules.sftp_worker import (MAX_READ_BYTES, READ_CAP_NONE, READ_ERROR_TOO_LARGE, SftpWorker,
                                 _SftpTask)
from ui import theme_qss

from _fakes import EventLog, FakeSftpClient, FakeSftpFS, wire_worker

LANGS = load_i18n_langs(ROOT)
# The pane FAMILY (the `sftp_tab.py` facade + its `sftp_pane_*.py` mixins): a text pin has to read
# the code WHEREVER the pane wave put it, or it stops protecting the day the cluster moves (1.8rc4).
PANE_SRC = pane_family_text(ROOT)
PANE_FILES = pane_family_files(ROOT)

TREE = os.path.join(WORK, "followup_tree")


def build_tree():
    """A real OS tree: two directories, three files of DIFFERENT sizes and three mtimes."""
    if os.path.isdir(TREE):
        shutil.rmtree(TREE, ignore_errors=True)
    os.makedirs(os.path.join(TREE, "zdir"))
    os.makedirs(os.path.join(TREE, "adir"))
    for name, data, mtime in (("b.txt", b"bbb", 1_700_000_300),
                              ("a.txt", b"a", 1_700_000_100),
                              ("c.txt", b"ccccc", 1_700_000_200)):
        path = os.path.join(TREE, name)
        with open(path, "wb") as f:
            f.write(data)
        os.utime(path, (mtime, mtime))
    return TREE


def real_file(name, size, data=b"x"):
    """A real file of exactly `size` bytes under WORK (the truncation samples)."""
    path = os.path.join(WORK, name)
    with open(path, "wb") as f:
        f.write(data * size)
    return path


def make_remote_tab(fs, commander=True):
    """(tab, worker, log) over the fake SFTP surface, optionally in the two-pane mode."""
    worker = SftpWorker(FakeSftpClient(fs))
    log = EventLog()
    wire_worker(worker, log)
    worker.start()
    tab = SftpTab()
    tab.message.connect(lambda *_a: None)
    if commander:
        tab.set_commander(True)
    tab.set_worker(worker)
    return tab, worker, log


def rows(pane):
    """The listing as `[(name, is_dir, size, mtime)]` — the ORDER is what the checks read."""
    out = []
    for i in range(pane.tree.topLevelItemCount()):
        item = pane.tree.topLevelItem(i)
        out.append((item.text(0), bool(item.data(0, pane.ISDIR_ROLE)),
                    int(item.data(0, pane.SIZE_ROLE) or 0),
                    int(item.data(0, pane.MTIME_ROLE) or 0)))
    return out


def names(pane):
    return [row[0] for row in rows(pane)]


def item_named(pane, name):
    for i in range(pane.tree.topLevelItemCount()):
        if pane.tree.topLevelItem(i).text(0) == name:
            return pane.tree.topLevelItem(i)
    return None


def wait_rows(pane, name, ms=10000):
    return wait_for(lambda: name in names(pane), timeout_ms=ms)


def click(pane, column):
    """ONE header click through the pane's own slot (the `sectionClicked` seam)."""
    pane._on_header_clicked(column)
    app.processEvents()


def set_sort(pane, column, descending):
    """Put the pane into a KNOWN sort state (the click machine is checked separately)."""
    pane._sort_column, pane._sort_desc = int(column), bool(descending)
    pane.apply_sort()
    app.processEvents()


print("== 1. the listing SORTS (ROADMAP v1.7.5, task 1) ==")

build_tree()
_fs = FakeSftpFS()
_fs.add_dir("/srv")
_fs.add_dir("/srv/zdir")
_fs.add_dir("/srv/adir")
_fs.add_file("/srv/b.txt", b"bbb", mtime=1_700_000_300)
_fs.add_file("/srv/a.txt", b"a", mtime=1_700_000_100)
_fs.add_file("/srv/c.txt", b"ccccc", mtime=1_700_000_200)

_tab, _worker, _log = make_remote_tab(_fs)
wait_rows(_tab.panes[0], "a.txt")
_rpane, _lpane = _tab.panes[0], _tab.panes[1]
_tab.set_pane_source(_lpane, SOURCE_LOCAL)
_lpane._relist(TREE)
wait_rows(_lpane, "a.txt")

check("§1 the row of a listing is the ROW SUBCLASS of the pane — both sources, ONE class",
      all(isinstance(_rpane.tree.topLevelItem(i), _SftpRowItem)
          for i in range(_rpane.tree.topLevelItemCount()))
      and all(isinstance(_lpane.tree.topLevelItem(i), _SftpRowItem)
              for i in range(_lpane.tree.topLevelItemCount())))
check("§1 ...and the comparison reads the ROLES (never the widget text)",
      all(hasattr(_SftpRowItem, n) for n in ("__lt__", "sort_key", "group_rank"))
      and row_name(item_named(_lpane, "a.txt")) == "a.txt"
      and row_path(item_named(_lpane, "a.txt")) == os.path.join(TREE, "a.txt")
      and int(item_named(_lpane, "a.txt").data(0, _lpane.ISDIR_ROLE)) == 0
      and {"ISDIR_ROLE", "SIZE_ROLE", "MTIME_ROLE", "PATH_ROLE"} <= set(dir(_lpane))
      and all(fragment in PANE_SRC for fragment in ("_SftpPane.ISDIR_ROLE", "pane.SIZE_ROLE",
                                                    "pane.MTIME_ROLE", "row_name(self)",
                                                    "row_path(self)")))
check("§1 the PROVIDER's own order is the default: directories first, then the name",
      names(_lpane) == ["..", "adir", "zdir", "a.txt", "b.txt", "c.txt"], str(names(_lpane)))
check("§1 Qt's own automatic sorting stays OFF — the pane drives `sortItems()` itself",
      _lpane.tree.isSortingEnabled() is False
      and _lpane.tree.header().sectionsClickable() is True
      and _lpane.tree.header().isSortIndicatorShown() is True
      and "tree.sortItems(self._sort_column, Qt.SortOrder.AscendingOrder)" in PANE_SRC)
check("§1 the sort state is a VIEW state of the pane — NO config key is written",
      "ui_sftp_sort" not in PANE_SRC
      and not any(str(k).startswith("ui_sftp_sort") for k in (read_cfg({}) or {}))
      and (_lpane._sort_column, _lpane._sort_desc) == (0, False))

# The three headers, BOTH directions, over a REAL local listing: the two declared rules hold.
for _column, _key, _key_index in ((0, "Name", 0), (1, "Size", 2), (2, "Modified", 3)):
    click(_lpane, _column)          # one click — the column is chosen, the direction follows it
    _first = rows(_lpane)
    click(_lpane, _column)          # the second click on the SAME column flips the direction
    _second = rows(_lpane)
    _k_first = [r[_key_index] for r in _first if not r[1]]
    _k_second = [r[_key_index] for r in _second if not r[1]]
    check(f"§1 a click on the {_key} header really sorts a REAL local listing",
          _k_first in (sorted(_k_first), sorted(_k_first, reverse=True))
          and _k_second == _k_first[::-1],
          f"first={_k_first} second={_k_second}")
    check(f"§1 ...and the two GROUP rules hold in BOTH directions for {_key}:"
          f" '..' first, the directories above the files",
          all(snap and snap[0][0] == ".." for snap in (_first, _second))
          and all([r[1] for r in snap[1:3]] == [True, True] for snap in (_first, _second))
          and all(not any(r[1] for r in snap[3:]) for snap in (_first, _second)),
          f"first={[r[0] for r in _first]} second={[r[0] for r in _second]}")

set_sort(_lpane, 1, True)   # Size, descending
check("§1 the Size header orders by the SIZE ROLE, not by the name",
      [r[0] for r in rows(_lpane) if not r[1]] == ["c.txt", "b.txt", "a.txt"],
      str(names(_lpane)))
set_sort(_lpane, 1, False)  # ...and ascending is the same key reversed
check("§1 ...and the ascending direction is the same key reversed",
      [r[2] for r in rows(_lpane) if not r[1]] == [1, 3, 5], str(rows(_lpane)))
set_sort(_lpane, 2, True)   # Modified, descending
check("§1 the Modified header orders by the MTIME ROLE",
      [r[3] for r in rows(_lpane) if not r[1]] == [1_700_000_300, 1_700_000_200, 1_700_000_100]
      and [r[0] for r in rows(_lpane) if not r[1]] == ["b.txt", "c.txt", "a.txt"],
      str(names(_lpane)))
check("§1 the column and its direction are ONE declared state, mirrored by the header arrow",
      (_lpane._sort_column, _lpane._sort_desc) == (2, True)
      and _lpane.tree.header().sortIndicatorSection() == 2
      and _lpane.tree.header().sortIndicatorOrder() == Qt.SortOrder.DescendingOrder)
_lpane._relist(TREE)
wait_rows(_lpane, "a.txt")
check("§1 a RE-LISTING keeps the chosen order (a view state, not a one-shot sort)",
      names(_lpane) == ["..", "zdir", "adir", "b.txt", "c.txt", "a.txt"], str(names(_lpane)))

# The SAME keys over a fake SERVER pane — the roles are the remote ones by construction.
_rpane._relist("/srv")
wait_rows(_rpane, "a.txt")
set_sort(_rpane, 0, False)
check("§1 the same header sorts a fake-SERVER listing by the same ROLES",
      names(_rpane) == ["..", "adir", "zdir", "a.txt", "b.txt", "c.txt"], str(names(_rpane)))
set_sort(_rpane, 1, False)
check("§1 ...and its Size column is the remote size from the listing",
      [r[2] for r in rows(_rpane) if not r[1]] == [1, 3, 5], str(rows(_rpane)))
set_sort(_rpane, 1, True)
check("§1 ...with the two GROUP rules in BOTH directions on that side too",
      names(_rpane) == ["..", "zdir", "adir", "c.txt", "b.txt", "a.txt"], str(names(_rpane)))

# A header click through QTest — the REAL control, not the slot (Qt gotcha #6). The tab must be a
# WINDOW: `QTest` delivers the click to the widget's window handle, and a child of a never-shown
# parent has none.
from PySide6.QtTest import QTest   # noqa: E402 — the mouse seam of the project

_tab.resize(900, 360)
_tab.show()
set_sort(_lpane, 1, False)          # a known starting point: the Size column, ascending
for _ in range(3):
    app.processEvents()
_modified_x = (_lpane.tree.header().sectionViewportPosition(2)
               + max(4, _lpane.tree.header().sectionSize(2) // 2))
QTest.mouseClick(_lpane.tree.header().viewport(), Qt.MouseButton.LeftButton,
                 Qt.KeyboardModifier.NoModifier, QPoint(_modified_x, 8))
app.processEvents()
check("§1 a REAL click on the header really sorts (the header is the control)",
      (_lpane._sort_column, _lpane._sort_desc) == (2, False)
      and names(_lpane) == ["..", "adir", "zdir", "a.txt", "c.txt", "b.txt"],
      f"col={_lpane._sort_column} desc={_lpane._sort_desc} rows={names(_lpane)}")

# The mc/far walk still works on the sorted rows (the keys act on the CURRENT row).
_lpane._move_cursor(_lpane.tree.topLevelItem(2))   # the pane's own cursor move (no selection)
_walk_row = _lpane._current_row()
check("§1 the keyboard walk still acts on the row the cursor is on (a sorted listing)",
      _walk_row is not None and _walk_row.text(0) == "zdir",
      f"current={_walk_row.text(0) if _walk_row else None} rows={names(_lpane)}")
_before_mark = _lpane._row_marked(_lpane.tree.topLevelItem(2))
_lpane._mark_current_row()
check("§1 ...and `Insert` toggles the mark and steps DOWN the sorted order",
      _lpane._row_marked(_lpane.tree.topLevelItem(2)) is (not _before_mark)
      and _lpane.tree.currentItem() is not None
      and _lpane.tree.currentItem().text(0) == "a.txt",
      f"before={_before_mark} after={_lpane._row_marked(_lpane.tree.topLevelItem(2))} "
      f"current={_lpane.tree.currentItem().text(0) if _lpane.tree.currentItem() else None}")


print("== 2. the preview CEILING (ROADMAP v1.7.5, task 2) ==")

check("§2 the ceiling is ONE config key with a DECLARED default (the shipped read policy)",
      STAB.VIEWER_MAX_BYTES_CONFIG == "ui_viewer_max_bytes"
      and STAB.VIEWER_MAX_BYTES_MIN == MAX_READ_BYTES
      and STAB.VIEWER_MAX_BYTES_MAX == 250 * 1024 * 1024
      and STAB.VIEWER_MAX_BYTES_WARN == 3 * 1024 * 1024
      and STAB.VIEWER_MAX_BYTES_STEP == 1024 * 1024
      and resolve_viewer_max_bytes({}) == MAX_READ_BYTES)
check("§2 the resolver clamps into the range and refuses a foreign value (PURE)",
      clamp_viewer_max_bytes(10 ** 12) == STAB.VIEWER_MAX_BYTES_MAX
      and clamp_viewer_max_bytes(1) == STAB.VIEWER_MAX_BYTES_MIN
      and clamp_viewer_max_bytes("nonsense") == STAB.VIEWER_MAX_BYTES_MIN
      and clamp_viewer_max_bytes(True) == STAB.VIEWER_MAX_BYTES_MIN
      and resolve_viewer_max_bytes({STAB.VIEWER_MAX_BYTES_CONFIG: 4 * MAX_READ_BYTES})
      == 4 * MAX_READ_BYTES
      and resolve_viewer_max_bytes({STAB.VIEWER_MAX_BYTES_CONFIG: "8"}) == MAX_READ_BYTES
      and resolve_viewer_max_bytes({STAB.VIEWER_MAX_BYTES_CONFIG: 2 ** 40})
      == STAB.VIEWER_MAX_BYTES_MAX)
clear_cfg()
check("§2 ...and it round-trips through config.json (a merge-write, clamped)",
      save_viewer_max_bytes(7 * MAX_READ_BYTES)
      and read_cfg({}).get(STAB.VIEWER_MAX_BYTES_CONFIG) == 7 * MAX_READ_BYTES
      and resolve_viewer_max_bytes() == 7 * MAX_READ_BYTES)
clear_cfg()
save_viewer_max_bytes(10 ** 12)
check("§2 an out-of-range write to config.json is CLAMPED, never stored raw",
      read_cfg({}).get(STAB.VIEWER_MAX_BYTES_CONFIG) == STAB.VIEWER_MAX_BYTES_MAX
      and resolve_viewer_max_bytes() == STAB.VIEWER_MAX_BYTES_MAX,
      str(read_cfg({}).get(STAB.VIEWER_MAX_BYTES_CONFIG)))
clear_cfg()

check("§2 the cap travels IN THE TASK — neither worker reads a config",
      "max_bytes" in _SftpTask.__slots__ and "max_bytes" in LFW._LocalTask.__slots__
      and READ_CAP_NONE == 0
      and "max_bytes" in str(inspect.signature(SftpWorker.queue_read))
      and "max_bytes" in str(inspect.signature(LFW.LocalFsWorker.queue_read))
      and "resolve_viewer_max_bytes" not in
      open(os.path.join(ROOT, "modules", "sftp_worker.py"), encoding="utf-8").read()
      and "resolve_viewer_max_bytes" not in
      open(os.path.join(ROOT, "modules", "local_fs_worker.py"), encoding="utf-8").read())

_big_remote = 2 * MAX_READ_BYTES + 17
_fs_big = FakeSftpFS()
_fs_big.add_dir("/logs")
_fs_big.add_file("/logs/app.log", b"L" * _big_remote)
_fs_big.add_file("/logs/exact.log", b"E" * MAX_READ_BYTES)
_w2 = SftpWorker(FakeSftpClient(_fs_big))
_l2 = EventLog()
wire_worker(_w2, _l2)
_w2.start()
_tid = _w2.queue_read("/logs/app.log", _big_remote, max_bytes=MAX_READ_BYTES)
wait_until(lambda: _l2.of_kind("read", _tid) or _l2.of_kind("error", _tid), timeout_ms=20000)
check("§2 the REMOTE provider TRUNCATES at the task's cap — never a refusal",
      bool(_l2.of_kind("read", _tid)) and not _l2.of_kind("error", _tid)
      and len(_l2.of_kind("read", _tid)[0][3]) == MAX_READ_BYTES,
      f"err={_l2.of_kind('error', _tid)}")
check("§2 ...and the bytes are the FIRST ones of the file, in order",
      _l2.of_kind("read", _tid)[0][3] == b"L" * MAX_READ_BYTES)
_tid_small = _w2.queue_read("/logs/app.log", _big_remote,
                            max_bytes=STAB.VIEWER_MAX_BYTES_MAX)
wait_until(lambda: _l2.of_kind("read", _tid_small), timeout_ms=20000)
check("§2 a cap above the file reads the WHOLE file (a ceiling, not a size)",
      len(_l2.of_kind("read", _tid_small)[0][3]) == _big_remote)
_tid_none = _w2.queue_read("/logs/app.log", _big_remote)
wait_until(lambda: _l2.of_kind("error", _tid_none), timeout_ms=20000)
check("§2 a task with NO cap keeps the shipped REFUSAL (an exact read: the history import)",
      bool(_l2.of_kind("error", _tid_none))
      and _l2.of_kind("error", _tid_none)[0][3] == READ_ERROR_TOO_LARGE)
# The boundary: ONE byte over the cap truncates, EXACTLY the cap reads whole.
_fs_big.add_file("/logs/over.log", b"E" * (MAX_READ_BYTES + 1))
_tid_edge = _w2.queue_read("/logs/over.log", MAX_READ_BYTES + 1, max_bytes=MAX_READ_BYTES)
wait_until(lambda: _l2.of_kind("read", _tid_edge), timeout_ms=20000)
check("§2 a file exactly ONE byte over the cap is truncated to the cap (never refused)",
      len(_l2.of_kind("read", _tid_edge)[0][3]) == MAX_READ_BYTES
      and _l2.of_kind("read", _tid_edge)[0][3] == b"E" * MAX_READ_BYTES)
_tid_exact = _w2.queue_read("/logs/exact.log", MAX_READ_BYTES, max_bytes=MAX_READ_BYTES)
wait_until(lambda: _l2.of_kind("read", _tid_exact), timeout_ms=20000)
check("§2 ...while a file exactly AT the cap is read WHOLE (a ceiling, not a size)",
      len(_l2.of_kind("read", _tid_exact)[0][3]) == MAX_READ_BYTES)
_w2.shutdown(wait_ms=2000)

_w3 = LFW.LocalFsWorker(root=WORK)
_l3 = EventLog()
wire_worker(_w3, _l3)
_w3.start()
_big_local = real_file("followup_big.log", _big_remote)
_tid_l = _w3.queue_read(_big_local, _big_remote, max_bytes=MAX_READ_BYTES)
wait_until(lambda: _l3.of_kind("read", _tid_l) or _l3.of_kind("error", _tid_l), timeout_ms=20000)
check("§2 the LOCAL provider shares the rule: the same task field, the same truncation",
      bool(_l3.of_kind("read", _tid_l)) and not _l3.of_kind("error", _tid_l)
      and len(_l3.of_kind("read", _tid_l)[0][3]) == MAX_READ_BYTES)
_tid_l0 = _w3.queue_read(_big_local, _big_remote)
wait_until(lambda: _l3.of_kind("error", _tid_l0), timeout_ms=20000)
check("§2 ...and a LOCAL read with no cap keeps the shipped refusal too",
      _l3.of_kind("error", _tid_l0)[0][3] == READ_ERROR_TOO_LARGE)
_w3.shutdown(wait_ms=2500)

# The PANE resolves the cap once, hands it to the task and says WHICH part is on the screen.
_fs_view = FakeSftpFS()
_fs_view.add_dir("/var")
_fs_view.add_file("/var/huge.log", b"H" * (3 * MAX_READ_BYTES), mtime=1_700_000_000)
_fs_view.add_file("/var/small.txt", b"tiny\n", mtime=1_700_000_000)
_tab4, _w4, _l4 = make_remote_tab(_fs_view, commander=False)
_p4 = _tab4.panes[0]
wait_rows(_p4, "var")
_p4._relist("/var")
wait_rows(_p4, "huge.log")
check("§2 the pane resolves the ceiling at construction (the shipped policy is the default)",
      _p4.viewer_cap() == MAX_READ_BYTES)
check("§2 the SIZE alone never marks a row — the cap truncates instead of refusing",
      preview_block_reason("/var/huge.log", 3 * MAX_READ_BYTES) == ""
      and item_named(_p4, "huge.log").toolTip(0) == "")
_msgs = []
_p4.message.connect(_msgs.append)
_p4._on_item_double_clicked(item_named(_p4, "huge.log"), 0)
wait_until(lambda: not _p4.viewer.isHidden(), timeout_ms=20000)
check("§2 a file over the cap OPENS in the panel — truncated, never refused",
      _p4.viewer.isHidden() is False and not _msgs
      and len(_p4.viewer_text.toPlainText()) == MAX_READ_BYTES,
      f"msgs={_msgs} len={len(_p4.viewer_text.toPlainText())}")
check("§2 ...and the header says 'the first N of M' (the listing knows the real size)",
      i18n.t("sftp.viewer.truncated", shown=format_size(MAX_READ_BYTES),
             total=format_size(3 * MAX_READ_BYTES)) in _p4.viewer_label.text(),
      f"got={_p4.viewer_label.text()!r}")
check("§2 ...while a file UNDER the cap carries no notice (the whole file is on the screen)",
      preview_block_reason("/var/small.txt", 5) == "")
_p4.close_viewer()

_p4._blocked["/var/huge.log"] = READ_ERROR_TOO_LARGE
_p4._mark_row("/var/huge.log")
check("§2 a fact of a REAL read is what marks a row",
      item_named(_p4, "huge.log").toolTip(0)
      == i18n.t("sftp.viewer.too_large", limit=format_size(MAX_READ_BYTES)))
check("§2 a new ceiling INVALIDATES the facts of the old one (a verdict belongs to its cap)",
      _p4.set_viewer_max_bytes(5 * MAX_READ_BYTES) == 5 * MAX_READ_BYTES
      and _p4.viewer_cap() == 5 * MAX_READ_BYTES
      and _p4._blocked == {}
      and item_named(_p4, "huge.log").toolTip(0) == "",
      str(_p4._blocked))
check("§2 ...and the container hands the new cap to EVERY pane (`apply_viewer_max_bytes`)",
      _tab4.apply_viewer_max_bytes(2 * MAX_READ_BYTES) == 2 * MAX_READ_BYTES
      and all(p.viewer_cap() == 2 * MAX_READ_BYTES for p in _tab4.panes))
check("§2 an out-of-range write is CLAMPED, never stored raw",
      _tab4.apply_viewer_max_bytes(10 ** 12) == STAB.VIEWER_MAX_BYTES_MAX
      and _tab4.apply_viewer_max_bytes(0) == STAB.VIEWER_MAX_BYTES_MIN
      and _tab4.panes[0].viewer_cap() == MAX_READ_BYTES)

_seen = {}
_orig_read = _w4.queue_read


def _spy_read(path, total_size=0, max_bytes=READ_CAP_NONE, _orig=_orig_read, _sink=_seen):
    _sink["cap"] = max_bytes
    return _orig(path, total_size, max_bytes=max_bytes)


_w4.queue_read = _spy_read
_p4._on_item_double_clicked(item_named(_p4, "small.txt"), 0)
wait_until(lambda: "cap" in _seen, timeout_ms=10000)
check("§2 the pane hands its OWN ceiling to the read task (one number, one home)",
      _seen.get("cap") == MAX_READ_BYTES, str(_seen))
_w4.queue_read = _orig_read
_p4.close_viewer()

# N46 (the READ PATH): a read the ceiling CUT must decode as the SOURCE's encoding, never as the
# consequence of the cut — the header then carries the truncation notice and NO encoding note.
_CYR_TEXT = ("\u0421\u0435\u0440\u0432\u0435\u0440: \u043f\u0440\u043e\u0434\u0430\u043a\u0448\u043d\n" * 8)
_CYR_FILE = _CYR_TEXT.encode("utf-8")
_fs_view.add_file("/var/cyr.txt", _CYR_FILE, mtime=1_700_000_000)
_p4._relist("/var")
wait_rows(_p4, "cyr.txt")
_CYR_CUT = 0
for _n in range(len(_CYR_FILE), 0, -1):
    try:
        _CYR_FILE[:_n].decode("utf-8-sig")
    except UnicodeDecodeError:
        _CYR_CUT = _n
        break
_CYR_HEAD = _CYR_FILE[:_CYR_CUT]
_CYR_INTACT = _CYR_TEXT[:len(_CYR_HEAD.decode("utf-8", errors="ignore"))]
_CYR_TID = 987_654
_p4._read_tasks[_CYR_TID] = "/var/cyr.txt"
_p4._last_read = _CYR_TID
_p4._on_read_ready(_CYR_TID, "/var/cyr.txt", _CYR_HEAD)
check("§2 N46 the probe really cuts a multi-byte character (the case the fix exists for)",
      _CYR_CUT and _CYR_HEAD[-1] >= 0xC0 and _CYR_INTACT, f"cut={_CYR_CUT}")
check("§2 N46 a read the ceiling CUT shows the REAL text of the prefix, not Latin-1 mojibake",
      _p4.viewer_text.toPlainText() == _CYR_INTACT and _p4.viewer_encoding == "utf-8",
      f"{_p4.viewer_encoding} / {len(_p4.viewer_text.toPlainText())}")
check("§2 N46 ...the header carries the TRUNCATION notice and NOT the encoding note",
      i18n.t("sftp.viewer.truncated", shown=format_size(_CYR_CUT),
             total=format_size(len(_CYR_FILE))) in _p4.viewer_label.text()
      and i18n.t("sftp.viewer.encoding_note", encoding="latin-1")
      not in _p4.viewer_label.text(),
      _p4.viewer_label.text())
check("§2 N46 ...while a COMPLETE Latin-1 file keeps the shipped answer (the counter-case)",
      STAB.decode_text(b"caf\xe9") == ("caf\xe9", "latin-1")
      and STAB.read_was_truncated(len(_CYR_HEAD), _p4.viewer_cap(),
                                  len(_CYR_FILE)) is True)
_p4.close_viewer()

# The settings hub's "Files" page is the UI of the key.
from ui.settings_dialog import SettingsDialog   # noqa: E402 — the hub is the setting's UI

_dlg = SettingsDialog(None)
_tab_texts = [_dlg.tabs.tabText(i) for i in range(_dlg.tabs.count())]
check("§2 the hub carries a 'Files' page for the reader's ceiling",
      i18n.t("settings.tab.files") in _tab_texts
      and _dlg.viewer_max_spin.minimum() == 1
      and _dlg.viewer_max_spin.maximum()
      == STAB.VIEWER_MAX_BYTES_MAX // STAB.VIEWER_MAX_BYTES_STEP,
      str(_tab_texts))
_dlg.viewer_max_spin.setValue(4)
_slider_followed = _dlg.viewer_max_slider.value()
_dlg.viewer_max_slider.setValue(6)
check("§2 the slider and the value box are ONE number (each writes the other)",
      _slider_followed == 4 and _dlg.viewer_max_spin.value() == 6)
check("§2 ...and the value travels to config.json in BYTES",
      _dlg.collect()["ui_viewer_max_bytes"] == 6 * STAB.VIEWER_MAX_BYTES_STEP,
      str(_dlg.collect()["ui_viewer_max_bytes"]))
_dlg.viewer_max_spin.setValue(2)
_warn_quiet = _dlg.viewer_max_warning.isHidden()
_dlg.viewer_max_spin.setValue(9)
check("§2 the warning appears exactly above the declared threshold",
      _warn_quiet is True and _dlg.viewer_max_warning.isHidden() is False)

# N57: the ceiling's GUI cost is a MEASURED number, and the warning is a VIEW of it.
check("§2 N57 `viewer_freeze_seconds()` is pure, monotone in the cap and never raises",
      STAB.viewer_freeze_seconds(1024 * 1024) == STAB.VIEWER_FREEZE_MS_PER_MB / 1000.0
      and STAB.viewer_freeze_seconds(32 * 1024 * 1024)
      > STAB.viewer_freeze_seconds(3 * 1024 * 1024) > 0.0
      and STAB.viewer_freeze_seconds(None) == 0.0
      and STAB.viewer_freeze_seconds("nonsense") == 0.0)
check("§2 N57 ...and the slope is the release's own measurement (32 MB ≈ 5.1 s, not 'a second')",
      4.5 <= STAB.viewer_freeze_seconds(32 * 1024 * 1024) <= 6.0,
      f"{STAB.viewer_freeze_seconds(32 * 1024 * 1024):.1f} s")
_dlg.viewer_max_spin.setValue(9)
check("§2 N57 the warning row PRINTS that number for the cap the user is choosing",
      _dlg.viewer_max_warning.text() == i18n.t(
          "settings.files.max_bytes_warning",
          seconds=f"{STAB.viewer_freeze_seconds(9 * STAB.VIEWER_MAX_BYTES_STEP):.1f}"),
      _dlg.viewer_max_warning.text())
check("§2 N57 ...and the SAME sentence is rebuilt on a language switch (no frozen literal)",
      all("{seconds}" in data["settings.files.max_bytes_warning"] for data in LANGS.values()))
_dlg.reject()

# N57: the parser's own contract — the verification has a DECLARED budget, above which the reader
# accepts the extension hint UNVERIFIED instead of freezing the GUI on a 250 MiB parse.
import modules.syntax_highlight as SH   # noqa: E402 — the verdict the reader asks for

check("§2 N57 `detect_syntax` is only asked to PARSE within its declared budget",
      SH.within_verify_budget("x" * 10) is True
      and SH.within_verify_budget("x" * (SH.SYNTAX_VERIFY_MAX_CHARS + 1)) is False
      and SH.detect_syntax("/etc/big.json", "x" * (SH.SYNTAX_VERIFY_MAX_CHARS + 1))
      == SH.LANG_NUMBERS
      and SH.detect_syntax("/etc/big.json", "x" * (SH.SYNTAX_VERIFY_MAX_CHARS + 1),
                           verify=False) == SH.LANG_JSON)
check("§2 N57 ...and the shipped verdict inside the budget is untouched (the honesty rule)",
      SH.detect_syntax("/etc/app.json", '{"a": 1}') == SH.LANG_JSON
      and SH.detect_syntax("/etc/app.json", '{"a": ') == SH.LANG_NUMBERS
      and SH.detect_syntax("/etc/svc.xml", "<a><b/></a>") == SH.LANG_XML
      and SH.detect_syntax("/etc/k8s.yaml", "a: 1") == SH.LANG_YAML)

check("§2 VERSION_FORMAT stays `0.9` (a ceiling is a value, not a schema)",
      __import__("version").VERSION_FORMAT == "0.9"
      and all(f"{d}>=" in open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read()
              for d in ("PySide6", "paramiko", "keyring", "wcwidth")))


print("== 3. the pane's SOURCE HEADER LINE (ROADMAP v1.7.5, task 3) ==")

check("§3 the header line is the pane's FIRST row, above the address bar",
      _lpane.layout().itemAt(0).widget() is _lpane.header_label
      and _lpane.layout().itemAt(1).layout() is not None
      and _lpane.layout().itemAt(1).layout().indexOf(_lpane.path_label) >= 0)
check("§3 a LOCAL pane names THIS machine; a pane nobody identified keeps the shipped wording",
      _lpane.header_text() == i18n.t("sftp.local.this_computer")
      and _tab4.panes[0].header_text() == i18n.t("sftp.waiting_connection"),
      f"local={_lpane.header_text()!r} remote={_tab4.panes[0].header_text()!r}")
_tab.set_session_info(key="followup", label="alpha", host="192.0.2.55", port=22, user="root")
check("§3 the session's ALIAS wins the moment the container is identified",
      _rpane.header_text() == "alpha"
      and _rpane.header_label.text() == _rpane.header_text_marked(),
      _rpane.header_text())
_tab.set_session_info(key="followup", label="", host="192.0.2.55", port=22, user="root")
check("§3 ...and `user@host` is the fallback when it was never identified",
      _rpane.header_text() == "root@192.0.2.55", _rpane.header_text())
check("§3 an alias is DATA — the local wording is the SHIPPED key, no new one was added",
      all(str(data.get("sftp.local.this_computer") or "").strip() for data in LANGS.values())
      and not any(k.startswith("sftp.remote.") for k in LANGS["en"]))
check("§3 the line takes NO keyboard walk and NO drop coordinates",
      _lpane.header_label.focusPolicy() == Qt.FocusPolicy.NoFocus
      and _lpane.header_label.wordWrap() is False
      and 'obj is getattr(self, "header_label", None)' in PANE_SRC
      and "self.tree.viewport().mapFrom(source, pos)" in PANE_SRC)
_hint_before = _lpane.header_label.sizeHint().height()
_lpane.header_label.setText("y" * 500)
check("§3 ...and it is ONE line of height whatever the text is",
      _lpane.header_label.sizeHint().height() == _hint_before
      and _hint_before <= 2 * _lpane.header_label.fontMetrics().height(),
      f"{_hint_before} -> {_lpane.header_label.sizeHint().height()}")
_lpane._sync_header()
check("§3 the ADDRESS BAR keeps the shipped wording (a path, never the source's name)",
      _lpane.path_label.text() == _lpane.current_dir
      and _lpane.path_label.text() != i18n.t("sftp.local.this_computer"))

# A language switch re-TEXTS the line, a theme switch re-STYLES it (the container's walks).
_en_text = _lpane.header_label.text()
_prev_lang = i18n.get_current_language()
try:
    i18n.set_language("ru")
    _tab.retranslate()
    _ru_text = _lpane.header_label.text()
    check("§3 a language switch re-texts the line through the pane's own key",
          _ru_text.replace(ACTIVE_PANE_MARK, "", 1).strip()
          == i18n.t("sftp.local.this_computer") and _ru_text != _en_text,
          f"en={_en_text!r} ru={_ru_text!r}")
finally:
    i18n.set_language(_prev_lang or "en")
    _tab.retranslate()
_tab.refresh_theme()
check("§3 a theme switch re-styles the line through the ONE registry key",
      theme_qss.style("status.sftp_row") in _lpane.header_label.styleSheet()
      and _lpane.header_label.text() == _lpane.header_text_marked(),
      _lpane.header_label.styleSheet()[:60])
check("§3 the single-pane views carry the line too (the session the pane belongs to)",
      len(_tab4.panes) == 1 and _tab4.panes[0].source_header_label() is not None)

_tab4.release()
_w4.shutdown()
_tab.release()
_worker.shutdown()


print("== 4. the release state ==")

check_i18n_parity(LANGS)
check_i18n_format(LANGS)
check_release_state(ROOT)
check("the follow-up's four keys exist in EVERY language",
      all(all(str(data.get(k) or "").strip() for data in LANGS.values())
          for k in ("settings.tab.files", "settings.files.max_bytes",
                    "settings.files.max_bytes_warning", "sftp.viewer.truncated")))
check("the i18n pin counts the slot's four keys (the v1.8 elevated pane's 20, the v1.8.1 trust "
      "surface's 41 and the ONE of v1.8.1.1) and v1.8.2 adds SIXTEEN: the library file — the History door, the backup ring and the import/export pair — and v1.8.3 adds TWENTY-THREE: the Plugins window (its chrome, its three columns and its export) and v1.8.4 adds TEN: the whole-map layout, the reverse traversal and the inode fact, and v1.9 adds FOUR: the production-tag guard — its title, the broadcast sentence and the paste sentence — and the notice of a checked selection that has left the map, and v1.9.1 adds ELEVEN: the reconnect and its `tmux attach`; v1.9.3 adds THIRTEEN: the command dialog's ten keys and the reader's encoding three; v1.9.6 adds THREE: the command guard's two sentences and the refusal line; v1.9.8 adds THIRTEEN: the two `Clear` asks with their hints and their title, the `Diagnostics ▸` submenu with its imperative row, the session tab's identity line, the two source-switch tooltips and the three fields of the Settings dialog's font row",
      EXPECTED_I18N_KEYS == 915 + 4 + 6 + 20 + 41 + 1 + 16 + 23 + 10 + 4 + 11 + 13 + 3 + 12 + 13 and releases_at_least(EXPECTED_APP_VERSION, "1.7.5"),
      f"{EXPECTED_I18N_KEYS} / {EXPECTED_APP_VERSION}")
finish()
