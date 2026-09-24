# -*- coding: utf-8 -*-
"""v1.1.3 — SFTP tab in the terminal window (ROADMAP v1.1.3, tasks 1–5).

The theme of the release: a new worker thread with the task queue (list/upload/download)
over the live transport + the UI tab [Terminal | Files]. ALL the checks —
without the network: a fake SFTPClient with an in-memory FS (the same API surface as
paramiko: listdir_attr/open/close/get_channel; the errors — the IOError "No such
file", like SSH_FX_NO_SUCH_FILE).

The sections:
  1. The fake FS + the worker: two uploads STRICTLY sequentially,
     the progress signals in order (the monotonicity, the final == total, the content).
  2. The path error → the error signal WITHOUT the queue crash (the listing of a nonexistent
     directory, the upload into a nonexistent directory; the following tasks work).
  3. The cancel: the flag between the operations — the current transfer is interrupted on the chunk,
     the queue is skipped with task_cancelled, the worker lives, the flag auto-resets.
     v1.3.3.2 rewrite of the pinned check: the upload is ATOMIC — a cancelled upload
     leaves the EXISTING remote file byte-identical and no `.part` file behind.
  4. The shutdown: the idle (fast) and during the transfer (within the wait budget),
     the SFTPClient is closed, the queue_* after the stop — None.
  5. The SftpTab offscreen: the listing/navigation without the network ("..", the directory enter,
     the Refresh, the stalking filter of the stale answers), the upload/download of the selected
     (the QFileDialog is patched), the "Cancel" button on the transfers.
  6. The SSHTerminalWindow offscreen: the QTabWidget [Terminal | Files], the lazy
     open_sftp() on the same transport, the connected_signal pickup, the
     open_sftp error → the status bar, the progress in the status bar, the closeEvent teardown.
  7. i18n: 21 keys sftp.* × en/ru/zh, the parity 377 → 398.
  8. The release state: APP_VERSION == "1.1.3", the pyproject cross-check, the
     requirements header.

Run:  python tests/test_sftp_tab.py   (from the project root) or python tests/run_all.py
"""
import os
import sys
import time

from _common import (bootstrap, check, finish, wait_until, load_i18n_langs, check_i18n_parity,
                     check_release_state)

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

import i18n
import modules.sftp_worker as SW
import modules.sftp_tab as STAB
from modules.sftp_worker import SftpWorker
from modules.sftp_tab import SftpTab, format_size, format_mtime

# The fake in-memory FS + the fake SFTPClient (no network) — the shared stubs _fakes.py
from _fakes import FakeSftpFS, FakeSftpClient, EventLog, wire_worker


def make_local_file(name, size, pattern=b"0"):
    p = os.path.join(WORK, name)
    with open(p, "wb") as f:
        f.write(pattern * size)
    return p


# ════════════════════════════════════════════════════════════
# 1. Worker: two uploads strictly in sequence + progress in order
# ════════════════════════════════════════════════════════════
print("== 1. worker: two uploads strictly sequential ==")

fs1 = FakeSftpFS()
client1 = FakeSftpClient(fs1, chunk_delay=0.005)  # the delay per chunk — the order is observed
worker1 = SftpWorker(client1)
log1 = EventLog()
wire_worker(worker1, log1)
worker1.start()

SIZE_A, SIZE_B = 4 * 32768, 3 * 32768  # 4 and 3 chunks of 32 KB each
local_a = make_local_file("a.bin", SIZE_A, b"a")
local_b = make_local_file("b.bin", SIZE_B, b"b")

tid_a = worker1.queue_upload(local_a, "/")
tid_b = worker1.queue_upload(local_b, "/")
check("the queue_upload returned the task ids (1, 2)", (tid_a, tid_b) == (1, 2),
      f"got={tid_a},{tid_b}")

wait_until(lambda: log1.of_kind("done", tid_b), timeout_ms=8000)
app.processEvents()

idx = {}
with log1.lock:
    for i, e in enumerate(log1.events):
        if len(e) > 1 and e[1] in (tid_a, tid_b):
            idx.setdefault(e[1], []).append(i)
last_a = max(idx.get(tid_a, [0]))
first_b = min(idx.get(tid_b, [len(log1.events)]))
check("strictly sequential: ALL the events of A before ANY of B", last_a < first_b,
      f"last_a={last_a} first_b={first_b}")

kinds_a = [log1.events[i][0] for i in idx.get(tid_a, [])]
check("A: started → progress* → done", kinds_a[:1] == ["started"]
      and kinds_a[-1] == "done" and all(k == "progress" for k in kinds_a[1:-1]),
      f"kinds={kinds_a}")

prog_a = [e[2] for e in log1.of_kind("progress", tid_a)]
check("A: the progress grows monotonically",
      prog_a and all(x <= y for x, y in zip(prog_a, prog_a[1:])), f"prog={prog_a}")
check("A: the final progress == the total (4 chunks)", prog_a[-1] == SIZE_A,
      f"last={prog_a[-1]} total={SIZE_A}")
prog_b = [e[2] for e in log1.of_kind("progress", tid_b)]
check("B: the final progress == the total (3 chunks)", prog_b and prog_b[-1] == SIZE_B,
      f"last={prog_b[-1] if prog_b else None} total={SIZE_B}")

check("the content of A on the 'server'", fs1.files.get("/a.bin") == b"a" * SIZE_A)
check("the content of B on the 'server'", fs1.files.get("/b.bin") == b"b" * SIZE_B)
done_a = log1.of_kind("done", tid_a)
check("the task_done A: the detail = the remote path", done_a and done_a[0][2] == "/a.bin",
      f"got={done_a}")

# a download in the reverse direction (the progress with the total from the listing)
local_dl = os.path.join(WORK, "dl")
os.makedirs(local_dl, exist_ok=True)
tid_dl = worker1.queue_download("/b.bin", local_dl, SIZE_B)
wait_until(lambda: log1.of_kind("done", tid_dl), timeout_ms=8000)
check("the download: the file on the disk with the same content",
      open(os.path.join(local_dl, "b.bin"), "rb").read() == b"b" * SIZE_B)

worker1.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 2. A path error → an error signal without the queue crashing
# ════════════════════════════════════════════════════════════
print("== 2. worker: path error → error signal, queue survives ==")

fs2 = FakeSftpFS()
worker2 = SftpWorker(FakeSftpClient(fs2))
log2 = EventLog()
wire_worker(worker2, log2)
worker2.start()

tid_err1 = worker2.queue_list("/nope")
wait_until(lambda: log2.of_kind("error", tid_err1), timeout_ms=5000)
err1 = log2.of_kind("error", tid_err1)[0]
check("the list of a nonexistent directory → task_error", "No such file" in err1[3],
      f"msg={err1[3]!r}")

tid_ok1 = worker2.queue_list("/")
wait_until(lambda: log2.of_kind("list", tid_ok1), timeout_ms=5000)
check("the queue is alive: the next list finished (list_ready)",
      bool(log2.of_kind("list", tid_ok1)))

tid_err2 = worker2.queue_upload(make_local_file("c.bin", 100, b"c"), "/nope")
wait_until(lambda: log2.of_kind("error", tid_err2), timeout_ms=5000)
check("the upload into a nonexistent directory → task_error",
      bool(log2.of_kind("error", tid_err2)))

tid_ok2 = worker2.queue_upload(make_local_file("d.bin", 100, b"d"), "/")
wait_until(lambda: log2.of_kind("done", tid_ok2), timeout_ms=5000)
check("the queue is alive after the errors: the valid upload finished",
      fs2.files.get("/d.bin") == b"d" * 100)

tid_err3 = worker2.queue_download("/nope/file.bin", WORK, 0)
wait_until(lambda: log2.of_kind("error", tid_err3), timeout_ms=5000)
check("the download of a nonexistent file → task_error",
      bool(log2.of_kind("error", tid_err3)))

worker2.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 3. Cancellation: a flag between operations, the queue is skipped, the flag auto-resets
# ════════════════════════════════════════════════════════════
print("== 3. worker: cancellation ==")

fs3 = FakeSftpFS()
# v1.3.3.2: the destination EXISTS — the pin of this section is the ATOMIC upload
# (ROADMAP task 6): a cancelled upload must not truncate the previous remote file.
fs3.add_file("/slow.bin", b"ORIGINAL")
client3 = FakeSftpClient(fs3, chunk_delay=0.02)  # ~10 chunks × 20 ms = 200 ms
worker3 = SftpWorker(client3)
log3 = EventLog()
wire_worker(worker3, log3)
worker3.start()

SLOW_SIZE = 10 * 32768
local_slow = make_local_file("slow.bin", SLOW_SIZE, b"s")
tid_slow = worker3.queue_upload(local_slow, "/")
tid_next = worker3.queue_upload(make_local_file("next.bin", 100, b"n"), "/")

wait_until(lambda: log3.of_kind("progress", tid_slow), timeout_ms=5000)
worker3.cancel()
wait_until(lambda: len(log3.of_kind("cancelled")) >= 2, timeout_ms=8000)

check("the current transfer is cancelled (task_cancelled)",
      bool(log3.of_kind("cancelled", tid_slow)))
check("the next one from the queue is skipped (task_cancelled)",
      bool(log3.of_kind("cancelled", tid_next)))
check("none of the cancelled ones finished (no task_done)",
      not log3.of_kind("done", tid_slow) and not log3.of_kind("done", tid_next))
prog_slow = [e[2] for e in log3.of_kind("progress", tid_slow)]
check("the transfer is interrupted BEFORE the end (the progress < the total)",
      prog_slow and prog_slow[-1] < SLOW_SIZE,
      f"last={prog_slow[-1] if prog_slow else None} total={SLOW_SIZE}")
# v1.3.3.2 (ROADMAP task 3/6): the PINNED behaviour of v1.1.3 — "a cancelled upload
# leaves a shorter file on the server" — is DELIBERATELY GONE. The upload goes to
# `/slow.bin.part` and is renamed on success, so a cancel leaves the previous remote
# file byte-identical and no provisional file behind.
partial = fs3.files.get("/slow.bin", b"")
check("v1.3.3.2: the cancelled upload left the EXISTING remote file intact (atomic)",
      partial == b"ORIGINAL", f"got={bytes(partial)[:40]!r}")
check("v1.3.3.2: the cancelled upload left no `.part` file on the 'server'",
      not [p for p in fs3.files if p.endswith(".part")], f"files={sorted(fs3.files)}")
check("the worker is alive after the cancellation", worker3.isRunning())

tid_after = worker3.queue_upload(make_local_file("after.bin", 100, b"f"), "/")
wait_until(lambda: log3.of_kind("done", tid_after), timeout_ms=5000)
check("the flag auto-reset: the new upload after the cancellation finished",
      fs3.files.get("/after.bin") == b"f" * 100)

worker3.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 4. Shutdown: idle and during a transfer; the SFTPClient is closed
# ════════════════════════════════════════════════════════════
print("== 4. worker: shutdown ==")

client4 = FakeSftpClient(FakeSftpFS())
worker4 = SftpWorker(client4)
worker4.start()
wait_until(lambda: worker4.isRunning(), timeout_ms=2000)
t0 = time.time()
worker4.shutdown(wait_ms=2000)
elapsed = time.time() - t0
check("the idle shutdown: the thread finished", not worker4.isRunning())
check("the idle shutdown: fast (< 1 s, not the whole wait budget)", elapsed < 1.0,
      f"elapsed={elapsed:.3f}")
check("the SFTPClient is closed in the finally run()", client4.closed)
check("the queue_* after the stop → None", worker4.queue_list("/") is None)

fs5 = FakeSftpFS()
client5 = FakeSftpClient(fs5, chunk_delay=0.05)  # ~7 chunks × 50 ms = 350 ms
worker5 = SftpWorker(client5)
log5 = EventLog()
wire_worker(worker5, log5)
worker5.start()
tid_mid = worker5.queue_upload(make_local_file("mid.bin", 7 * 32768, b"m"), "/")
wait_until(lambda: log5.of_kind("progress", tid_mid), timeout_ms=5000)
t0 = time.time()
worker5.shutdown(wait_ms=2000)
elapsed = time.time() - t0
check("the shutdown during the transfer: the thread finished", not worker5.isRunning())
check("the shutdown fit into the wait budget (+the margin)", elapsed < 2.3,
      f"elapsed={elapsed:.3f}")
# the queued signals are delivered via the event loop — we wait before checking
wait_until(lambda: log5.of_kind("cancelled", tid_mid), timeout_ms=3000)
check("the transfer at the stop reported the task_cancelled",
      bool(log5.of_kind("cancelled", tid_mid)))
check("the SFTPClient is closed (during the transfer)", client5.closed)


# ════════════════════════════════════════════════════════════
# 5. SftpTab: listing/navigating without network + uploading/downloading the selected
# ════════════════════════════════════════════════════════════
print("== 5. sftp tab: listing/navigation (offscreen, no network) ==")

fs6 = FakeSftpFS()
fs6.add_dir("/var")
fs6.add_dir("/home")
fs6.add_file("/home/a.txt", b"x" * 100)
fs6.add_file("/home/b.log", b"y" * 2048)
fs6.add_dir("/home/sub")
client6 = FakeSftpClient(fs6, chunk_delay=0.01)  # the stalking scenario is observed
worker6 = SftpWorker(client6)
log6 = EventLog()
wire_worker(worker6, log6)
worker6.start()

tab = SftpTab()
msgs = []
tab.message.connect(msgs.append)
tab.set_worker(worker6)  # → _relist("/")

# v1.3.3.2: the BUTTON SET is unchanged — the file operations of the version live in
# the tree's context menu, they did not add a sixth/… button to the tab.
check("the button set of the tab is the five v1.1.3 buttons (the operations are menu items)",
      [b.text() for b in (tab.btn_up, tab.btn_refresh, tab.btn_upload,
                          tab.btn_download, tab.btn_cancel)]
      == [i18n.t("sftp.up"), i18n.t("sftp.refresh"), i18n.t("sftp.upload"),
          i18n.t("sftp.download"), i18n.t("sftp.cancel")],
      f"got={[b.text() for b in (tab.btn_up, tab.btn_upload, tab.btn_cancel)]}")

wait_until(lambda: tab.tree.topLevelItemCount() >= 2, timeout_ms=5000)
names = [tab.tree.topLevelItem(i).text(0) for i in range(tab.tree.topLevelItemCount())]
check("the listing of the root: the home/var directories (no '..' at /)", names == ["home", "var"],
      f"names={names}")
check("the path_label = the current directory", tab.path_label.text() == "/",
      f"got={tab.path_label.text()!r}")
check("the btn_up is disabled at /", not tab.btn_up.isEnabled())

# Entering /home (a double click on the directory row — a direct slot call)
item_home = tab.tree.topLevelItem(0)
tab._on_item_double_clicked(item_home, 0)
wait_until(lambda: tab.tree.topLevelItemCount() >= 4, timeout_ms=5000)
names = [tab.tree.topLevelItem(i).text(0) for i in range(tab.tree.topLevelItemCount())]
check("the move into /home: the '..' is first", names[0] == "..", f"names={names}")
check("the composition of /home: the .., the sub directory first, then the files by the name",
      names == ["..", "sub", "a.txt", "b.log"], f"names={names}")
check("path_label = /home", tab.path_label.text() == "/home")
check("the btn_up is enabled outside /", tab.btn_up.isEnabled())

item_sub = tab.tree.topLevelItem(1)
item_a = tab.tree.topLevelItem(2)
item_b = tab.tree.topLevelItem(3)
check("the file's size in the column (100 B)", item_a.text(1) == "100 B",
      f"got={item_a.text(1)!r}")
check("the file's size 2048 → '2.0 KB'", item_b.text(1) == "2.0 KB",
      f"got={item_b.text(1)!r}")
check("the mtime is formatted (not empty)", len(item_a.text(2)) == 16,
      f"got={item_a.text(2)!r}")
check("the PATH_ROLE — the full path", item_a.data(0, tab.PATH_ROLE) == "/home/a.txt")
check("the ISDIR_ROLE: the sub directory is marked", item_sub.data(0, tab.ISDIR_ROLE) is True)

# Back via ".." (a double click on the ".." row)
tab._on_item_double_clicked(tab._up_item, 0)
wait_until(lambda: [tab.tree.topLevelItem(i).text(0)
                    for i in range(tab.tree.topLevelItemCount())] == ["home", "var"],
           timeout_ms=5000)
check("the '..' — the return to the root (without the '..' row)", tab.path_label.text() == "/")

# The "Up" button = the same thing (first down, then go_up())
tab._navigate("/home")
wait_until(lambda: tab.path_label.text() == "/home", timeout_ms=5000)
tab.go_up()
wait_until(lambda: tab.path_label.text() == "/", timeout_ms=5000)
check("the 'Up' button: /home → /", tab.path_label.text() == "/")

# The stalking filter: a navigation while an old listing is flying (chunk_delay=10 ms)
tab._navigate("/home")      # the list A is in the path
tab.go_up()                 # the list B is in the path; the current = "/"
wait_until(lambda: log6.of_kind("list", None) and tab.tree.topLevelItemCount() >= 2
           and tab.path_label.text() == "/", timeout_ms=5000)
names = [tab.tree.topLevelItem(i).text(0) for i in range(tab.tree.topLevelItemCount())]
check("the stalking filter: the answer of the CURRENT directory is rendered (the root, no '..')",
      names == ["home", "var"], f"names={names}")

# Refresh — re-listing the same directory
n_before = tab.tree.topLevelItemCount()
tab.btn_refresh.click()
wait_until(lambda: tab.tree.topLevelItemCount() == n_before, timeout_ms=5000)
check("the Refresh: the listing is rebuilt (the same entries)",
      [tab.tree.topLevelItem(i).text(0) for i in range(tab.tree.topLevelItemCount())]
      == ["home", "var"])

# ── the upload via the tab (QFileDialog is patched at the module level) ──
up_local = make_local_file("upload_via_tab.txt", 256, b"u")


class _FakeDialog:
    @staticmethod
    def getOpenFileNames(*a, **k):
        return ([up_local], "")

    @staticmethod
    def getExistingDirectory(*a, **k):
        d = os.path.join(WORK, "dl2")  # the real dialog returns an EXISTING directory
        os.makedirs(d, exist_ok=True)
        return d


saved_dialog = STAB.QFileDialog
STAB.QFileDialog = _FakeDialog
try:
    tab._navigate("/home")
    wait_until(lambda: tab.path_label.text() == "/home", timeout_ms=5000)
    done_before = len(log6.of_kind("done"))
    tab.btn_upload.click()
    # We await task_done, not the appearance in fs6.files: open("wb") creates the record BEFORE
    # the chunk records — waiting for the existence gives a race with a flying upload.
    wait_until(lambda: len(log6.of_kind("done")) >= done_before + 1, timeout_ms=5000)
    check("the upload through the tab → the file in the CURRENT directory (/home)",
          fs6.files.get("/home/upload_via_tab.txt") == b"u" * 256)

    # downloading the selected (a.txt + b.log) into the local directory
    wait_until(lambda: tab.tree.topLevelItemCount() >= 4, timeout_ms=5000)
    tab.tree.clearSelection()
    tab.tree.topLevelItem(2).setSelected(True)  # a.txt
    tab.tree.topLevelItem(3).setSelected(True)  # b.log
    done_before = len(log6.of_kind("done"))
    tab.btn_download.click()
    # We await BOTH task_done, not isfile(): the file exists on disk before the write
    # of the chunks (open "wb") — waiting on their presence races with a running download.
    wait_until(lambda: len(log6.of_kind("done")) >= done_before + 2, timeout_ms=5000)
    check("the download of the selected: the a.txt is downloaded with the content",
          open(os.path.join(WORK, "dl2", "a.txt"), "rb").read() == b"x" * 100)
    check("the download of the selected: the b.log is downloaded with the content",
          open(os.path.join(WORK, "dl2", "b.log"), "rb").read() == b"y" * 2048)

    # a download without a selection — a message() hint, nothing in the queue
    msgs.clear()
    tab.tree.clearSelection()
    tab.btn_download.click()
    check("the download without a selection → the message 'Select one or more files to download'",
          msgs == [i18n.t("sftp.no_selection")], f"msgs={msgs}")

    # an upload/download without the worker — a "waiting for the connection" hint
    tab.set_worker(None)
    check("no worker: the 'waiting' state (the path_label)",
          tab.path_label.text() == i18n.t("sftp.waiting_connection"),
          f"got={tab.path_label.text()!r}")
    # The buttons in the waiting state are disabled (the hint — the path_label above);
    # there is nothing to click, message() is not emitted here.
    check("no worker: the navigation/operation buttons are disabled",
          not tab.btn_up.isEnabled() and not tab.btn_refresh.isEnabled()
          and not tab.btn_upload.isEnabled() and not tab.btn_download.isEnabled())

    # The "Cancel" button for transfers: a slow upload → cancel → a reset
    slow_fs = FakeSftpFS()
    slow_fs.add_dir("/data")  # a non-empty root — there is something to render in the listing
    slow_client = FakeSftpClient(slow_fs, chunk_delay=0.05)
    worker_s = SftpWorker(slow_client)
    log_s = EventLog()
    wire_worker(worker_s, log_s)
    worker_s.start()
    tab.set_worker(worker_s)
    wait_until(lambda: tab.tree.topLevelItemCount() >= 1, timeout_ms=5000)
    check("the 'Cancel' button is disabled before the transfers", not tab.btn_cancel.isEnabled())
    slow_local = make_local_file("slow_tab.bin", 8 * 32768, b"t")
    _FakeDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([slow_local], ""))
    tab.btn_upload.click()
    wait_until(lambda: tab.btn_cancel.isEnabled(), timeout_ms=5000)
    check("the 'Cancel' button is enabled during the transfer", tab.btn_cancel.isEnabled())
    tab.btn_cancel.click()
    wait_until(lambda: not tab.btn_cancel.isEnabled(), timeout_ms=8000)
    check("after the cancellation: the 'Cancel' button is disabled again",
          not tab.btn_cancel.isEnabled())
    worker_s.shutdown(wait_ms=2000)
finally:
    STAB.QFileDialog = saved_dialog

worker6.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 6. SSHTerminalWindow: QTabWidget + a lazy open_sftp on the shared transport
# ════════════════════════════════════════════════════════════
print("== 6. terminal window: tabs + lazy open_sftp (offscreen) ==")

import modules.ssh_terminal as ST
from models.server import ServerData

# The §6 harness — the shared stubs _fakes.py (a channel without a write, send_data — a no-op in essence)
from _fakes import FakeSSHThread as _FakeSSHThread, FakeSSHClient as _FakeSshClient


_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeSSHThread  # all the terminal windows in this file — on the fake

_term_windows = []


def make_win(alias, ssh_client=None):
    """The terminal window with the fake thread; ssh_client — the "already connected"
    paramiko client (or None — the connection is not ready yet)."""
    w = ST.SSHTerminalWindow(
        ServerData(id=f"sftp-{alias}", alias=alias, host="10.99.0.1", user="root"),
        None, password="pw")
    _term_windows.append(w)
    w.resize(700, 500)
    w.terminal_thread.client = ssh_client
    return w


# ── Scenario A: the connection is ready, the switch to "Files" opens SFTP ──
fs_first = FakeSftpFS()
fs_first.add_dir("/data")  # a non-empty root — there is something to render in the listing
first_sftp = FakeSftpClient(fs_first)
win_a = make_win("a", _FakeSshClient(first_sftp))
check("a QTabWidget with three tabs (Terminal | Files | History — v1.5.7)",
      win_a.tabs.count() == 3)
check("the tab titles: Terminal | Files | History (the i18n en)",
      win_a.tabs.tabText(0) == i18n.t("sftp.tab_terminal")
      and win_a.tabs.tabText(1) == i18n.t("sftp.tab_files")
      and win_a.tabs.tabText(2) == i18n.t("terminal.tab_history"),
      f"got={win_a.tabs.tabText(0)!r}/{win_a.tabs.tabText(1)!r}/{win_a.tabs.tabText(2)!r}")
check("the worker is NOT created before the move to the tab (the lazy start)",
      win_a._sftp_worker is None)
# isHidden() — the flag of the widget itself: the window is not show()n in the test, hence
# isVisible() (which accounts for the ancestors) would be False even after show().
check("the progress bar is in the status bar, hidden", win_a._sftp_progress.isHidden())

win_a.tabs.setCurrentIndex(1)
wait_until(lambda: win_a._sftp_worker is not None and win_a._sftp_worker.isRunning(),
           timeout_ms=5000)
check("the move to the 'Files' → open_sftp() + the worker is running", win_a._sftp_worker is not None)
wait_until(lambda: win_a.sftp_tab.tree.topLevelItemCount() >= 1, timeout_ms=5000)
check("the listing of the root in the tab (through the shared transport)",
      win_a.sftp_tab.path_label.text() == "/")

# A repeated navigation — idempotent (the same worker)
w_ref = win_a._sftp_worker
win_a.tabs.setCurrentIndex(0)
win_a.tabs.setCurrentIndex(1)
check("the repeated start is idempotent (the same worker)", win_a._sftp_worker is w_ref)

# "The session died": the transport is closed → the worker notices the dead channel, by itself
# stops and the window resets the state (the finished signal).
first_sftp.close()
wait_until(lambda: win_a._sftp_worker is None, timeout_ms=5000)
check("the death of the transport → the worker stopped by itself, the window's state is reset",
      win_a._sftp_worker is None)

# A new connection (a slow SFTP client) — a repeated lazy start
fsA = FakeSftpFS()
fsA.add_dir("/data")
slow_client_a = FakeSftpClient(fsA, chunk_delay=0.05)  # ~400 ms for the upload
win_a.terminal_thread.client = _FakeSshClient(slow_client_a)
win_a.tabs.setCurrentIndex(0)
win_a.tabs.setCurrentIndex(1)
wait_until(lambda: win_a._sftp_worker is not None and win_a._sftp_worker.isRunning()
           and win_a._sftp_worker is not w_ref, timeout_ms=5000)
check("the repeated start after the reset — a NEW worker", win_a._sftp_worker is not w_ref)
wait_until(lambda: win_a.sftp_tab.tree.topLevelItemCount() >= 1, timeout_ms=5000)

# The progress in the status bar: a slow upload via the tab
saved_dialog = STAB.QFileDialog
STAB.QFileDialog = _FakeDialog
try:
    big_local = make_local_file("big_win.bin", 8 * 32768, b"z")
    _FakeDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([big_local], ""))
    win_a.sftp_tab.btn_upload.click()
    wait_until(lambda: not win_a._sftp_progress.isHidden(), timeout_ms=5000)
    check("the progress bar is visible during the transfer", not win_a._sftp_progress.isHidden())
    wait_until(lambda: "%" in (win_a.statusBar().currentMessage() or ""), timeout_ms=8000)
    msg = win_a.statusBar().currentMessage()
    check("the status bar: the progress text with the percentages", "%" in msg and "big_win.bin" in msg,
          f"msg={msg!r}")
    wait_until(lambda: win_a._sftp_progress.isHidden(), timeout_ms=8000)
    check("after the finish: the progress bar is hidden", win_a._sftp_progress.isHidden())
finally:
    STAB.QFileDialog = saved_dialog

# closeEvent: teardown of the SFTP worker + the terminal thread (idle — fast)
t0 = time.time()
win_a.close()
elapsed = time.time() - t0
app.processEvents()
check("the closeEvent of the window with the living worker: no crashes, < 4 s", elapsed < 4.0,
      f"elapsed={elapsed:.3f}")
wait_until(lambda: len(SW._orphan_workers) == 0, timeout_ms=5000)
check("the orphan-workers registry is empty after the close", len(SW._orphan_workers) == 0)

# ── Scenario B: the user is on "Files" during the connection ──
win_b = make_win("b")  # client=None — still connecting
win_b.tabs.setCurrentIndex(1)
app.processEvents()
check("without a connection: the worker is not created", win_b._sftp_worker is None)
check("without a connection: the tab is in the waiting state",
      win_b.sftp_tab.path_label.text() == i18n.t("sftp.waiting_connection"),
      f"got={win_b.sftp_tab.path_label.text()!r}")

# "The connection is complete": the client appeared + connected_signal
win_b.terminal_thread.client = _FakeSshClient(FakeSftpClient(FakeSftpFS()))
win_b.terminal_thread.connected_signal.emit()
wait_until(lambda: win_b._sftp_worker is not None and win_b._sftp_worker.isRunning(),
           timeout_ms=5000)
check("the connected_signal → the SFTP is opened (the user is already on the tab)",
      win_b._sftp_worker is not None)
win_b.close()

# ── Scenario C: open_sftp failed (the subsystem is off) — the error in the status bar ──
win_c = make_win("c", _FakeSshClient(None))  # a client whose open_sftp raises
win_c.tabs.setCurrentIndex(1)
app.processEvents()
check("the open_sftp crashed: the worker is not created", win_c._sftp_worker is None)
msg_c = win_c.statusBar().currentMessage() or ""
check("the open_sftp crashed: the error is in the status bar (the i18n sftp.open_failed)",
      "SFTP" in msg_c, f"msg={msg_c!r}")
win_c.close()

ST.SSHTerminalThread = _orig_thread_cls  # return the original class


# ════════════════════════════════════════════════════════════
# 7. i18n: 21 sftp.* keys × en/ru/zh, parity 377 → 398
# ════════════════════════════════════════════════════════════
print("== 7. i18n: sftp.* keys x3, parity 398 ==")

SFTP_KEYS = [
    "sftp.tab_terminal", "sftp.tab_files", "sftp.up", "sftp.refresh",
    "sftp.upload", "sftp.download", "sftp.cancel", "sftp.column_name",
    "sftp.column_size", "sftp.column_modified", "sftp.waiting_connection",
    "sftp.listing", "sftp.uploading", "sftp.downloading", "sftp.progress",
    "sftp.transfer_done", "sftp.transfer_cancelled", "sftp.no_selection",
    "sftp.upload_dialog_title", "sftp.download_dir_title", "sftp.open_failed",
]
check("exactly 21 sftp.* keys are used in the code", len(SFTP_KEYS) == 21)

for code in ("en", "ru", "zh"):
    i18n.set_language(code)
    missing = [k for k in SFTP_KEYS if i18n.t(k) == k or not i18n.t(k).strip()]
    check(f"{code}: all the 21 sftp.* keys are translated (not empty, not the raw ones)",
          not missing, f"missing={missing}")

i18n.set_language("en")  # return the default for cleanliness

check_i18n_parity(load_i18n_langs(ROOT))

# format_size/format_mtime — pure functions (the status bar progress text)
check("format_size: 0/1023/1024/1536/1MB",
      (format_size(0), format_size(1023), format_size(1024),
       format_size(1536), format_size(1024 * 1024))
      == ("0 B", "1023 B", "1.0 KB", "1.5 KB", "1.0 MB"))
check("format_size: the broken values → '?'",
      format_size(None) == "?" and format_size(-5) == "?")
check("format_mtime: the zero/broken → empty; the valid one — 16 characters",
      format_mtime(0) == "" and format_mtime(None) == ""
      and len(format_mtime(1700000000)) == 16)


# ════════════════════════════════════════════════════════════
# 8. Release state (pins — tests/_common.py: EXPECTED_APP_VERSION)
# ════════════════════════════════════════════════════════════
print("== 8. release state ==")
check_release_state(ROOT)

finish()
