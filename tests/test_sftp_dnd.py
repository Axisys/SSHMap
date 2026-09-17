# -*- coding: utf-8 -*-
"""v1.2.8 — D&D of files from Windows Explorer into the SFTP tab (ROADMAP v1.2.8).

The theme of the release: the SftpTab accepts the drop of the files (the URLs from QMimeData) → the upload through
the worker queue of v1.1.3 into the CURRENT shown directory; several files =
the sequential tasks of the queue; the progress — in the status bar of the window (the responsibility
of the window, not the tab); the errors (no connection / no permission / the path error) —
the error signal WITHOUT the queue crash.

ALL the checks — without the network: a fake SFTPClient with an in-memory FS (the same surface
of the API as paramiko: listdir_attr/open/close/get_channel; the errors — the IOError
"No such file" like the SSH_FX_NO_SUCH_FILE and the PermissionError "Permission denied")
+ the simulation of the drag via the synthetic QDragEnterEvent/QDropEvent with the QMimeData
(the URLs of the real local files from the working folder of the test).

The offscreen nuance (established by the probing, PySide6 6.11): the synthetic drag events
do NOT pass through the real DnD path of the Qt notify() (the childAt/spontaneous — their
delivery to the widgets under the cursor is not available from Python and bypasses the event filters),
therefore the delivery in the test — by the direct virtual calls
(`tab.dragEnterEvent(ev)` / `tab.dropEvent(ev)`) and the direct
`tab.eventFilter(child, ev)` for the routing of the events from the CHILDREN. This is exactly the
logic of the handlers that serves the real drop from the Explorer:
in the production Qt delivers the event to the widget under the cursor (the tree/viewport/the buttons —
to the children of the tab), the eventFilter forwards it to the handlers of the TAB ITSELF
(see the docstring of modules/sftp_tab.py, v1.2.8).

The sections:
  1. _local_files(mime): the filtering of the URLs (files/directories/non-local/
     nonexistent/empty).
  2. The drag simulation on the tab: the dragEnter accepts with the files / rejects without;
     the drop → the uploads go through the worker queue STRICTLY sequentially,
     the progress signals in order (the monotonicity, the final == total), the content on
     the "server", the hint drop_queued (count+dir); the target = the CURRENT directory.
  3. The routing via eventFilter: the drag events on the children (the viewport of the tree,
     the button) are forwarded and consumed (True), the non-drag events pass
     by (False), the foreign widgets are not touched; the drop on a child = the same
     result as on the tab itself; an empty drop (only the directories) —
     the hint drop_no_files.
  4. The errors via the drop path: no connection → waiting_connection + nothing
     into the queue; the remote directory vanished / no write permission → task_error,
     the queue lives, the following drops finish.
  5. i18n: sftp.drop_queued/sftp.drop_no_files × en/ru/zh (translated,
     the {count}/{dir} formatting), the parity 427.
  6. The release state (the pins — tests/_common.py).

Run:  python tests/test_sftp_dnd.py   (from the project root) or python tests/run_all.py
"""
import os
import sys

from _common import bootstrap, check, finish, wait_until, load_i18n_langs, check_i18n_parity, check_release_state

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from PySide6.QtCore import QEvent, QPoint, Qt, QUrl, QMimeData
try:
    from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
except ImportError:  # pragma: no cover — a safety net for other PySide6 builds
    from PySide6.QtWidgets import QDragEnterEvent, QDragMoveEvent, QDropEvent  # type: ignore
from PySide6.QtWidgets import QApplication, QWidget

app = QApplication(sys.argv)

import i18n
from modules.sftp_worker import SftpWorker
from modules.sftp_tab import SftpTab


# ════════════════════════════════════════════════════════════
# The fake in-memory FS + the fake SFTPClient (no network) — _fakes.py
# (deny_write/remove_dir — the §5/§6 scenarios of this test)
# ════════════════════════════════════════════════════════════

from _fakes import FakeSftpFS, FakeSftpClient, EventLog, wire_worker


def make_local_file(name, size, pattern=b"0"):
    p = os.path.join(WORK, name)
    with open(p, "wb") as f:
        f.write(pattern * size)
    return p


# ── The drag simulation: QMimeData + the synthetic events (see the docstring) ───────

def mime_with(*paths):
    """QMimeData with the URLs of local paths (what a drop from the Explorer carries)."""
    m = QMimeData()
    m.setUrls([QUrl.fromLocalFile(p) for p in paths])
    return m


def drag_enter_event(mime, pos=QPoint(10, 10)):
    return QDragEnterEvent(pos, Qt.DropAction.CopyAction, mime,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)


def drop_event(mime, pos=QPoint(10, 10)):
    return QDropEvent(pos, Qt.DropAction.CopyAction, mime,
                      Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)


def upload_starts(log):
    """task_started with kind == 'upload' (the queue order)."""
    with log.lock:
        return [e for e in log.events if e[0] == "started" and e[2] == "upload"]


# ════════════════════════════════════════════════════════════
# 1. _local_files(mime): filtering drag-and-drop URLs
# ════════════════════════════════════════════════════════════
print("== 1. _local_files: URL filtering ==")

lf_a = make_local_file("lf_a.bin", 10, b"a")
lf_b = make_local_file("lf_b.bin", 10, b"b")
lf_dir = os.path.join(WORK, "somedir")
os.makedirs(lf_dir, exist_ok=True)

# QUrl.toLocalFile() returns paths with SLASHES (F:/...) — we compare via normpath
def _normpaths(paths):
    return [os.path.normpath(p) for p in paths]


m_mixed = mime_with(lf_a, lf_dir, lf_b)
got = SftpTab._local_files(m_mixed)
check("only the files (the directory is skipped), the order is kept", _normpaths(got) == [lf_a, lf_b],
      f"got={got}")

m_nonlocal = QMimeData()
m_nonlocal.setUrls([QUrl.fromLocalFile(lf_a), QUrl("https://example.com/x.bin")])
got_nl = SftpTab._local_files(m_nonlocal)
check("the non-local URL (https) is skipped", _normpaths(got_nl) == [lf_a],
      f"got={got_nl}")

m_missing = mime_with(os.path.join(WORK, "no_such_file.bin"))
check("the nonexistent local path is skipped", SftpTab._local_files(m_missing) == [])

m_text = QMimeData()
m_text.setText("hello")
check("the drag without the URLs (the text) → empty", SftpTab._local_files(m_text) == [])
check("the None mime → empty", SftpTab._local_files(None) == [])


# ════════════════════════════════════════════════════════════
# 2. Drag simulation on the tab: drop → the worker queue, strictly in sequence
# ════════════════════════════════════════════════════════════
print("== 2. drag simulation: drop -> worker queue, strictly sequential ==")

fs = FakeSftpFS()
fs.add_dir("/data")
client = FakeSftpClient(fs, chunk_delay=0.005)  # the delay per chunk — the order is observed
worker = SftpWorker(client)
log = EventLog()
wire_worker(worker, log)
worker.start()

tab = SftpTab()
msgs = []
tab.message.connect(msgs.append)
tab.set_worker(worker)  # → _relist("/")

wait_until(lambda: tab.tree.topLevelItemCount() >= 1, timeout_ms=5000)
check("the listing of the root (the data directory)",
      [tab.tree.topLevelItem(i).text(0) for i in range(tab.tree.topLevelItemCount())] == ["data"],
      f"got={[tab.tree.topLevelItem(i).text(0) for i in range(tab.tree.topLevelItemCount())]}")

# Entering /data — the drop target = the CURRENT directory (not the root)
tab._navigate("/data")
wait_until(lambda: tab.path_label.text() == "/data", timeout_ms=5000)

SIZE_A, SIZE_B = 4 * 32768, 3 * 32768  # 4 and 3 chunks of 32 KB each
drop_a = make_local_file("drop_a.bin", SIZE_A, b"a")
drop_b = make_local_file("drop_b.bin", SIZE_B, b"b")

# a dragEnter with files → accept; without local files → no accept
m_ab = mime_with(drop_a, drop_b)
ev_in = drag_enter_event(m_ab)
tab.dragEnterEvent(ev_in)
check("the dragEnter with the files: accepted (acceptProposedAction)", ev_in.isAccepted())

m_text2 = QMimeData()
m_text2.setText("no files here")
ev_in2 = drag_enter_event(m_text2)
tab.dragEnterEvent(ev_in2)
check("the dragEnter without the local files: NOT accepted", not ev_in2.isAccepted())

# a drop → BOTH files through the queue (sequential tasks, v1.1.3)
msgs.clear()
ev_drop = drop_event(m_ab)
tab.dropEvent(ev_drop)
check("the drop with the files: accepted", ev_drop.isAccepted())

wait_until(lambda: len(upload_starts(log)) >= 2, timeout_ms=5000)
starts = upload_starts(log)
check("the two uploads went through the queue (task_started × 2)", len(starts) == 2,
      f"got={starts}")
tid_a, tid_b = starts[0][1], starts[1][1]
check("the task ids are sequential (the queue order)", tid_b == tid_a + 1,
      f"a={tid_a} b={tid_b}")
wait_until(lambda: bool(log.of_kind("done", tid_a)) and bool(log.of_kind("done", tid_b)),
           timeout_ms=8000)
app.processEvents()

idx = {}
with log.lock:
    for i, e in enumerate(log.events):
        if len(e) > 1 and e[1] in (tid_a, tid_b):
            idx.setdefault(e[1], []).append(i)
last_a = max(idx.get(tid_a, [0]))
first_b = min(idx.get(tid_b, [len(log.events)]))
check("strictly sequential: ALL the events of A before ANY of B", last_a < first_b,
      f"last_a={last_a} first_b={first_b}")

kinds_a = [log.events[i][0] for i in idx.get(tid_a, [])]
check("A: started → progress* → done", kinds_a[:1] == ["started"]
      and kinds_a[-1] == "done" and all(k == "progress" for k in kinds_a[1:-1]),
      f"kinds={kinds_a}")

prog_a = [e[2] for e in log.of_kind("progress", tid_a)]
check("A: the progress grows monotonically",
      prog_a and all(x <= y for x, y in zip(prog_a, prog_a[1:])), f"prog={prog_a}")
check("A: the final progress == the total (4 chunks)", prog_a[-1] == SIZE_A,
      f"last={prog_a[-1] if prog_a else None} total={SIZE_A}")
prog_b = [e[2] for e in log.of_kind("progress", tid_b)]
check("B: the final progress == the total (3 chunks)", prog_b and prog_b[-1] == SIZE_B,
      f"last={prog_b[-1] if prog_b else None} total={SIZE_B}")

check("the content of A on the 'server' in the CURRENT directory (/data)",
      fs.files.get("/data/drop_a.bin") == b"a" * SIZE_A)
check("the content of B on the 'server' in /data", fs.files.get("/data/drop_b.bin") == b"b" * SIZE_B)

expected_msg = i18n.t("sftp.drop_queued", count=2, dir="/data")
check("the hint after the drop: the drop_queued (count=2, dir=/data)", msgs == [expected_msg],
      f"msgs={msgs} expected={[expected_msg]}")


# ════════════════════════════════════════════════════════════
# 3. Routing via eventFilter: drag events on the tab's children
# ════════════════════════════════════════════════════════════
print("== 3. routing via eventFilter: drag events on children ==")

# a drop on the tree viewport (a child) — the filter forwards it to the handlers of the tree ITSELF
# the tabs and consumes the event (the tree does not handle it "its own way")
vp = tab.tree.viewport()
drop_c = make_local_file("drop_child.bin", 1024, b"c")
m_c = mime_with(drop_c)
ev_child = drop_event(m_c)
consumed = tab.eventFilter(vp, ev_child)
check("the eventFilter(viewport, Drop): the event is consumed (True)", consumed is True,
      f"got={consumed}")

n_starts_before = len(upload_starts(log))
wait_until(lambda: len(upload_starts(log)) > n_starts_before
           and bool(log.of_kind("done", upload_starts(log)[-1][1])), timeout_ms=5000)
check("the drop on a child (the viewport): the upload finished in the current directory",
      fs.files.get("/data/drop_child.bin") == b"c" * 1024,
      f"got={fs.files.get('/data/drop_child.bin')!r}")

# a dragEnter on a button — also forwarded (the drop target does not depend on the point)
m_c2 = mime_with(drop_c)
ev_btn_in = drag_enter_event(m_c2)
consumed2 = tab.eventFilter(tab.btn_upload, ev_btn_in)
check("the eventFilter(btn_upload, DragEnter): forwarded and accepted",
      consumed2 is True and ev_btn_in.isAccepted(), f"got={consumed2}")

# a non-drag event passes by (False) — the handlers are not called
ev_other = QEvent(QEvent.Type.FocusIn)
r = tab.eventFilter(vp, ev_other)
check("the eventFilter(viewport, non-drag): passes by (False)", r is False, f"got={r}")

# a foreign widget (not a descendant of the tab) — we do not touch it even for Drop
foreign = QWidget()
m_f = mime_with(drop_c)
ev_foreign = drop_event(m_f)
r2 = tab.eventFilter(foreign, ev_foreign)
check("the eventFilter(a foreign widget, Drop): not consumed (False), the event is not accepted",
      r2 is False and not ev_foreign.isAccepted(), f"got={r2}")

# A DragMove on a child — the same answer as dragEnter (otherwise Qt resets the action)
m_mv = mime_with(drop_c)
ev_move = QDragMoveEvent(QPoint(5, 5), Qt.DropAction.CopyAction, m_mv,
                         Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
r3 = tab.eventFilter(vp, ev_move)
check("the eventFilter(viewport, DragMove): forwarded and accepted",
      r3 is True and ev_move.isAccepted(), f"got={r3}")

# an empty drop (only directories in the drag) — a hint, nothing in the queue
msgs.clear()
m_dirs = mime_with(lf_dir)
ev_dirs = drop_event(m_dirs)
tab.dropEvent(ev_dirs)
check("the drop without the local files: NOT accepted", not ev_dirs.isAccepted())
check("the hint drop_no_files (the dragged directories)",
      msgs == [i18n.t("sftp.drop_no_files")], f"msgs={msgs}")


# ════════════════════════════════════════════════════════════
# 4. Errors via the drop path: the queue does not crash (the v1.1.3 test pattern)
# ════════════════════════════════════════════════════════════
print("== 4. errors via drop path: queue survives ==")

# a) no connection: a "waiting" hint, nothing goes into the queue
tab.set_worker(None)
check("no worker: the 'waiting' state (the path_label)",
      tab.path_label.text() == i18n.t("sftp.waiting_connection"),
      f"got={tab.path_label.text()!r}")
msgs.clear()
m_nw = mime_with(drop_c)
ev_nowork = drop_event(m_nw)
tab.dropEvent(ev_nowork)
check("the drop without a connection: the hint waiting_connection",
      msgs == [i18n.t("sftp.waiting_connection")], f"msgs={msgs}")

# b) a path error: the remote directory disappeared on the server BETWEEN the listing and the drop
fs2 = FakeSftpFS()
fs2.add_dir("/data")
worker2 = SftpWorker(FakeSftpClient(fs2))
log2 = EventLog()
wire_worker(worker2, log2)
worker2.start()

tab2 = SftpTab()
msgs2 = []
tab2.message.connect(msgs2.append)
tab2.set_worker(worker2)
wait_until(lambda: tab2.tree.topLevelItemCount() >= 1, timeout_ms=5000)
tab2._navigate("/data")
wait_until(lambda: tab2.path_label.text() == "/data", timeout_ms=5000)

fs2.remove_dir("/data")  # the directory disappeared on the server (the listing → drop race)
err_a = make_local_file("err_a.bin", 100, b"e")
err_b = make_local_file("err_b.bin", 100, b"f")
m_err = mime_with(err_a, err_b)
ev_err = drop_event(m_err)
tab2.dropEvent(ev_err)

wait_until(lambda: len(log2.of_kind("error")) >= 2, timeout_ms=8000)
errs = log2.of_kind("error")
check("the upload into a remote (vanished) directory → task_error × 2", len(errs) == 2,
      f"got={errs}")
check("the error's text — 'No such file' (SSH_FX_NO_SUCH_FILE)",
      all(len(e) > 3 and "No such file" in e[3] for e in errs),
      f"msgs={[e[3] for e in errs]}")

# the queue is alive: the directory is "restored" → the next drop finishes normally
fs2.add_dir("/data")
err_c = make_local_file("err_c.bin", 100, b"g")
n_before = len(upload_starts(log2))
m_ok = mime_with(err_c)
ev_ok = drop_event(m_ok)
tab2.dropEvent(ev_ok)


def _ok_after_error():
    starts_now = upload_starts(log2)
    return len(starts_now) > n_before and bool(log2.of_kind("done", starts_now[-1][1]))


wait_until(_ok_after_error, timeout_ms=8000)
check("the queue is alive after the path errors: the next drop finished",
      fs2.files.get("/data/err_c.bin") == b"g" * 100)

# c) no permissions: open("wb") → PermissionError; the queue is alive for the other paths
fs3 = FakeSftpFS(deny_write=frozenset({"/ro/perm.bin"}))
fs3.add_dir("/ro")
fs3.add_dir("/rw")
worker3 = SftpWorker(FakeSftpClient(fs3))
log3 = EventLog()
wire_worker(worker3, log3)
worker3.start()

tab3 = SftpTab()
msgs3 = []
tab3.message.connect(msgs3.append)
tab3.set_worker(worker3)
wait_until(lambda: tab3.tree.topLevelItemCount() >= 2, timeout_ms=5000)
tab3._navigate("/ro")
wait_until(lambda: tab3.path_label.text() == "/ro", timeout_ms=5000)

perm_local = make_local_file("perm.bin", 100, b"h")
m_perm = mime_with(perm_local)
ev_perm = drop_event(m_perm)
tab3.dropEvent(ev_perm)

wait_until(lambda: len(log3.of_kind("error")) >= 1, timeout_ms=8000)
errp = log3.of_kind("error")[0]
check("the upload without the write permission → task_error (PermissionError)",
      len(errp) > 3 and "Permission denied" in errp[3], f"msg={errp[3]!r}")

tab3._navigate("/rw")
wait_until(lambda: tab3.path_label.text() == "/rw", timeout_ms=5000)
m_rw = mime_with(perm_local)
ev_rw = drop_event(m_rw)
tab3.dropEvent(ev_rw)
wait_until(lambda: fs3.files.get("/rw/perm.bin") is not None, timeout_ms=8000)
check("the queue is alive after the permission error: the drop into the writable directory finished",
      fs3.files.get("/rw/perm.bin") == b"h" * 100)

worker2.shutdown(wait_ms=2000)
worker3.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 5. i18n: sftp.drop_* × en/ru/zh, parity 427
# ════════════════════════════════════════════════════════════
print("== 5. i18n: sftp.drop_* keys x3, parity 427 ==")

for code in ("en", "ru", "zh"):
    i18n.set_language(code)
    q = i18n.t("sftp.drop_queued", count=3, dir="/x")
    check(f"{code}: the sftp.drop_queued is translated and formatted ({{count}}/{{dir}} are substituted)",
          q != "sftp.drop_queued" and "{count}" not in q and "{dir}" not in q
          and "3" in q and "/x" in q, f"got={q!r}")
    n = i18n.t("sftp.drop_no_files")
    check(f"{code}: the sftp.drop_no_files is translated (not empty, not the raw key)",
          n != "sftp.drop_no_files" and bool(n.strip()), f"got={n!r}")

i18n.set_language("en")  # return the default for cleanliness

check_i18n_parity(load_i18n_langs(ROOT))


# ════════════════════════════════════════════════════════════
# 6. Release state (pins — tests/_common.py: EXPECTED_APP_VERSION)
# ════════════════════════════════════════════════════════════
print("== 6. release state ==")
check_release_state(ROOT)

worker.shutdown(wait_ms=2000)
finish()
