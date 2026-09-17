# -*- coding: utf-8 -*-
"""v1.3.3.2 — SFTP as a file manager: the operations + a transfer that does not lose data.

ROADMAP v1.3.3.2, tasks 1–6. The tab of v1.1.3 could only upload and download, and both
directions opened the destination with "wb" — an existing file was silently truncated on
the server and on the local disk alike. This version closes the operations gap and the
data-loss gap:

  1. the file operations mkdir/rename/delete join the SAME worker queue (the client stays
     single-threaded; a failing operation reports task_error and the queue lives on) and
     the tree gets a context menu — New folder / Rename / Delete / Copy remote path;
  2. the overwrite conflict (the deferred v1.3 promise): Overwrite / Skip / Rename /
     "Apply to all" for upload AND download, a cancelled dialog = skip;
  3. the download is ATOMIC: `<dest>.part` + os.replace — a cancelled one leaves the
     destination byte-identical;
  6. the upload is ATOMIC: `<remote>.part` + rename (posix-rename when the server knows
     it) — an interrupted upload never truncates the existing remote file.

Everything is checked offscreen and without the network: the in-memory fake SFTP of
tests/_fakes.py (which learned mkdir/rmdir/remove/rename/posix_rename in the same
release) + the synthetic drag events (the test_sftp_dnd.py delivery pattern: the drag is
delivered by direct virtual calls, the drop through `eventFilter` with the TREE VIEWPORT
as the source — exactly the widget Qt delivers a real drop to).

Sections:
  1. The worker: mkdir / rename / delete — the fake FS and the listing.
  2. A failing operation → task_error and the NEXT task still runs.
  3. Atomic upload: a cancelled one leaves the old remote file intact, the commit works
     with and without posix-rename.
  4. Atomic download: no `.part` after a success, a cancelled one leaves the destination
     byte-identical.
  5. The context menu (the `_build_context_menu(item)` seam) — the four operations.
  6. The operations through the tab: New folder / Rename / Delete / Copy remote path,
     with the listing refresh and the validation of the name.
  7. The conflict dialog: Overwrite / Skip / Rename / Apply-to-all over a batch, a
     cancelled dialog, and the same for the download direction.
  8. A drop onto a DIRECTORY ROW uploads into THAT directory (the pre-flight listing).
  9. Drag-out: the mime carries the remote path; the tree is drag-enabled.
 10. i18n (17 new keys × en/ru/zh/de) + the release state.

Run:  python tests/test_sftp_ops.py   (from the project root) or python tests/run_all.py
"""
import os
import sys
import time

from _common import (bootstrap, check, finish, wait_until, load_i18n_langs,
                     check_i18n_parity, check_release_state, i18n_lang_codes)

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from PySide6.QtCore import QEvent, QPoint, Qt, QUrl, QMimeData
try:
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
except ImportError:  # pragma: no cover — a safety net for other PySide6 builds
    from PySide6.QtWidgets import QDragEnterEvent, QDropEvent  # type: ignore
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

import i18n
import modules.sftp_tab as STAB
from modules.sftp_worker import (SftpWorker, KIND_MKDIR, KIND_RENAME, KIND_DELETE,
                                 OP_KINDS, PART_SUFFIX)

from _fakes import FakeSftpFS, FakeSftpClient, EventLog, wire_worker


def make_local_file(name, size, pattern=b"0"):
    p = os.path.join(WORK, name)
    with open(p, "wb") as f:
        f.write(pattern * size)
    return p


def make_local_text(name, text: bytes):
    p = os.path.join(WORK, name)
    with open(p, "wb") as f:
        f.write(text)
    return p


def item_by_name(tab, name):
    for i in range(tab.tree.topLevelItemCount()):
        it = tab.tree.topLevelItem(i)
        if it.text(0) == name:
            return it
    return None


def no_part_files(fs):
    """The provisional files left on the 'server' (must always be empty)."""
    return [p for p in fs.files if p.endswith(PART_SUFFIX)]


def local_parts(directory):
    return [f for f in os.listdir(directory) if f.endswith(PART_SUFFIX)]


def mime_with(*paths):
    m = QMimeData()
    m.setUrls([QUrl.fromLocalFile(p) for p in paths])
    return m


def drop_event(mime, pos=QPoint(10, 10)):
    return QDropEvent(pos, Qt.DropAction.CopyAction, mime,
                      Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)


def upload_starts(log):
    with log.lock:
        return [e for e in log.events if e[0] == "started" and e[2] == "upload"]


# ── The dialog seams of the tab (module attributes) ─────────────────────────

class _FakeButton:
    def __init__(self, text):
        self._text = text

    def text(self):
        return self._text


class _FakeMessageBox:
    """The QMessageBox stand-in of the tab: the DELETE confirmation (the static
    `question()`) AND the CONFLICT dialog (the instance API + its QCheckBox).

    SCRIPT — the scripted answers of the conflict dialogs, one tuple per question:
    ("overwrite" | "skip" | "rename" | None, apply_all); None = a cancelled dialog.
    DIALOGS — what every dialog showed (title, text, the button labels).
    """

    Yes = 1
    No = 0
    CONFIRM = True
    SCRIPT = []
    DIALOGS = []

    class Icon:
        Question = 0

    class ButtonRole:
        AcceptRole = 0
        RejectRole = 1
        ActionRole = 2

    def __init__(self, parent=None):
        self._buttons = {}
        self._checkbox = None
        self._clicked = None
        self.title = ""
        self.text = ""

    @staticmethod
    def question(*args, **kwargs):
        return _FakeMessageBox.Yes if _FakeMessageBox.CONFIRM else _FakeMessageBox.No

    def setWindowTitle(self, text):
        self.title = text

    def setIcon(self, icon):
        pass

    def setText(self, text):
        self.text = text

    def addButton(self, text, role=None):
        button = _FakeButton(text)
        self._buttons[text] = button
        return button

    def setCheckBox(self, box):
        self._checkbox = box

    def exec(self):
        action, apply_all = (self.SCRIPT.pop(0) if self.SCRIPT else ("skip", False))
        labels = {"overwrite": i18n.t("sftp.conflict.overwrite"),
                  "skip": i18n.t("sftp.conflict.skip"),
                  "rename": i18n.t("sftp.conflict.rename")}
        self._clicked = self._buttons.get(labels.get(action)) if action else None
        if self._checkbox is not None:
            self._checkbox.setChecked(bool(apply_all) and action is not None)
        apply_label = self._checkbox.text() if self._checkbox is not None else ""
        self.DIALOGS.append((self.title, self.text, sorted(self._buttons), apply_label))

    def clickedButton(self):
        return self._clicked


class _FakeInputDialog:
    """QInputDialog.getText — a script of names ([]) = the dialog was cancelled)."""

    SCRIPT = []

    @staticmethod
    def getText(*args, **kwargs):
        if _FakeInputDialog.SCRIPT:
            return (_FakeInputDialog.SCRIPT.pop(0), True)
        return ("", False)


class _FakeFileDialog:
    FILES = []
    DIR = ""

    @staticmethod
    def getOpenFileNames(*args, **kwargs):
        return (list(_FakeFileDialog.FILES), "")

    @staticmethod
    def getExistingDirectory(*args, **kwargs):
        return _FakeFileDialog.DIR


def make_tab(fs, chunk_delay=0.0):
    """(tab, worker, log, client) with the listing of "/" already rendered."""
    client = FakeSftpClient(fs, chunk_delay=chunk_delay)
    worker = SftpWorker(client)
    log = EventLog()
    wire_worker(worker, log)
    worker.start()
    tab = STAB.SftpTab()
    tab.message.connect(lambda *_a: None)
    tab.set_worker(worker)
    wait_until(lambda: tab.tree.topLevelItemCount() >= 1, timeout_ms=5000)
    return tab, worker, log, client


_SAVED = (STAB.QMessageBox, STAB.QInputDialog, STAB.QFileDialog)
STAB.QMessageBox = _FakeMessageBox
STAB.QInputDialog = _FakeInputDialog
STAB.QFileDialog = _FakeFileDialog


# ════════════════════════════════════════════════════════════
# 1. The worker: mkdir / rename / delete
# ════════════════════════════════════════════════════════════
print("== 1. worker: the three file operations ==")

fs1 = FakeSftpFS()
fs1.add_dir("/home")
fs1.add_dir("/home/sub")
fs1.add_file("/home/a.txt", b"alpha")
worker1 = SftpWorker(FakeSftpClient(fs1))
log1 = EventLog()
wire_worker(worker1, log1)
worker1.start()

tid_mk = worker1.queue_mkdir("/home", "fresh")
wait_until(lambda: log1.of_kind("done", tid_mk), timeout_ms=5000)
check("mkdir created the directory on the 'server'", "/home/fresh" in fs1.dirs,
      f"dirs={sorted(fs1.dirs)}")
check("mkdir's task_done detail is the new path",
      log1.of_kind("done", tid_mk)[0][2] == "/home/fresh",
      f"got={log1.of_kind('done', tid_mk)}")
check("the operation kinds are the documented ones",
      OP_KINDS == (KIND_MKDIR, KIND_RENAME, KIND_DELETE) == ("mkdir", "rename", "delete"),
      f"got={OP_KINDS}")

tid_ls = worker1.queue_list("/home")
wait_until(lambda: log1.of_kind("list", tid_ls), timeout_ms=5000)
names = [e["name"] for e in log1.of_kind("list", tid_ls)[0][3]]
check("the new directory is in the listing", "fresh" in names, f"names={names}")
check("the listing puts it with the directories (before the files)",
      names.index("fresh") < names.index("a.txt"), f"names={names}")

tid_ren = worker1.queue_rename("/home/a.txt", "b.txt")
wait_until(lambda: log1.of_kind("done", tid_ren), timeout_ms=5000)
check("rename moved the file in the fake FS",
      "/home/b.txt" in fs1.files and "/home/a.txt" not in fs1.files,
      f"files={sorted(fs1.files)}")
check("rename keeps the CONTENT untouched", fs1.files.get("/home/b.txt") == b"alpha")
check("rename's detail is the new path",
      log1.of_kind("done", tid_ren)[0][2] == "/home/b.txt")

tid_ren_dir = worker1.queue_rename("/home/fresh", "renamed")
wait_until(lambda: log1.of_kind("done", tid_ren_dir), timeout_ms=5000)
check("a DIRECTORY can be renamed too",
      "/home/renamed" in fs1.dirs and "/home/fresh" not in fs1.dirs,
      f"dirs={sorted(fs1.dirs)}")

tid_del = worker1.queue_delete("/home/b.txt")
wait_until(lambda: log1.of_kind("done", tid_del), timeout_ms=5000)
check("delete removed the file", "/home/b.txt" not in fs1.files)
check("delete of a FILE reported no error", not log1.of_kind("error", tid_del))

tid_del_dir = worker1.queue_delete("/home/renamed", True)
wait_until(lambda: log1.of_kind("done", tid_del_dir), timeout_ms=5000)
check("delete removed the EMPTY directory", "/home/renamed" not in fs1.dirs,
      f"dirs={sorted(fs1.dirs)}")
check("the whole batch left no provisional file behind", no_part_files(fs1) == [])

worker1.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 2. A failing operation → task_error; the queue lives on
# ════════════════════════════════════════════════════════════
print("== 2. worker: a failing operation does not kill the queue ==")

fs2 = FakeSftpFS()
fs2.add_dir("/home")
fs2.add_dir("/home/nonempty")
fs2.add_file("/home/nonempty/inside.txt", b"i")
fs2.add_file("/home/keep.txt", b"k")
fs2.add_dir("/ro", )
worker2 = SftpWorker(FakeSftpClient(fs2))
log2 = EventLog()
wire_worker(worker2, log2)
worker2.start()

tid_bad = worker2.queue_mkdir("/home", "nonempty")   # already exists
wait_until(lambda: log2.of_kind("error", tid_bad), timeout_ms=5000)
check("mkdir over an existing entry → task_error", bool(log2.of_kind("error", tid_bad)))
check("the failed mkdir did not touch the directory",
      fs2.files.get("/home/nonempty/inside.txt") == b"i")

tid_rm_bad = worker2.queue_delete("/home/nonempty", True)   # not empty
wait_until(lambda: log2.of_kind("error", tid_rm_bad), timeout_ms=5000)
check("rmdir of a NON-EMPTY directory → task_error (not recursive)",
      bool(log2.of_kind("error", tid_rm_bad)), f"events={log2.events}")
check("the non-empty directory survived the refusal", "/home/nonempty" in fs2.dirs)

tid_ren_bad = worker2.queue_rename("/home/missing.txt", "x.txt")
wait_until(lambda: log2.of_kind("error", tid_ren_bad), timeout_ms=5000)
check("rename of a missing path → task_error", bool(log2.of_kind("error", tid_ren_bad)))

tid_ok = worker2.queue_rename("/home/keep.txt", "kept.txt")
wait_until(lambda: log2.of_kind("done", tid_ok), timeout_ms=5000)
check("the QUEUE IS ALIVE after the three failures (the next task ran)",
      fs2.files.get("/home/kept.txt") == b"k")

worker2.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 3. Atomic upload (ROADMAP task 6)
# ════════════════════════════════════════════════════════════
print("== 3. worker: the upload is atomic ==")

fs3 = FakeSftpFS()
fs3.add_dir("/home")
fs3.add_file("/home/target.bin", b"OLD" * 100)   # 300 bytes of "the previous version"
client3 = FakeSftpClient(fs3, chunk_delay=0.02)
worker3 = SftpWorker(client3)
log3 = EventLog()
wire_worker(worker3, log3)
worker3.start()

slow_local = make_local_file("target_local.bin", 8 * 32768, b"n")
tid_up = worker3.queue_upload(slow_local, "/home")
wait_until(lambda: log3.of_kind("progress", tid_up), timeout_ms=5000)
worker3.cancel()
wait_until(lambda: log3.of_kind("cancelled", tid_up), timeout_ms=8000)

check("the cancelled upload reported task_cancelled",
      bool(log3.of_kind("cancelled", tid_up)))
check("the OLD remote file is byte-identical after the cancelled upload",
      fs3.files.get("/home/target.bin") == b"OLD" * 100,
      f"len={len(fs3.files.get('/home/target.bin', b''))}")
check("the cancelled upload left no provisional file on the 'server'",
      no_part_files(fs3) == [], f"files={sorted(fs3.files)}")
check("the upload did NOT go through the destination name directly (no truncation)",
      len(fs3.files.get("/home/target.bin", b"")) == 300)

# The queue lives on: a successful upload replaces the file in ONE step.
small_local = make_local_file("target_local2.bin", 100, b"z")
tid_up2 = worker3.queue_upload(small_local, "/home", remote_name="target.bin")
wait_until(lambda: log3.of_kind("done", tid_up2), timeout_ms=5000)
check("a successful upload replaced the content",
      fs3.files.get("/home/target.bin") == b"z" * 100)
check("a successful upload leaves no provisional file",
      no_part_files(fs3) == [], f"files={sorted(fs3.files)}")
check("the task_done detail is the FINAL path",
      log3.of_kind("done", tid_up2)[0][2] == "/home/target.bin")

# A server WITHOUT posix-rename@openssh.com: the v3 rename + the cleared destination.
client3.posix_rename_ok = False
tid_up3 = worker3.queue_upload(small_local, "/home", remote_name="target.bin")
wait_until(lambda: log3.of_kind("done", tid_up3), timeout_ms=5000)
check("the upload commits on a server without posix-rename (the remove+rename fallback)",
      fs3.files.get("/home/target.bin") == b"z" * 100)
check("the fallback left no provisional file either", no_part_files(fs3) == [])

# A brand-new name still works without posix-rename (a plain v3 rename).
tid_up4 = worker3.queue_upload(small_local, "/home", remote_name="brand_new.bin")
wait_until(lambda: log3.of_kind("done", tid_up4), timeout_ms=5000)
check("a new name lands on the 'server' with the fallback path",
      fs3.files.get("/home/brand_new.bin") == b"z" * 100)

worker3.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 4. Atomic download (ROADMAP task 3)
# ════════════════════════════════════════════════════════════
print("== 4. worker: the download is atomic ==")

dl_dir = os.path.join(WORK, "dl_atomic")
os.makedirs(dl_dir, exist_ok=True)

fs4 = FakeSftpFS()
fs4.add_dir("/home")
fs4.add_file("/home/small.txt", b"x" * 200)
client4 = FakeSftpClient(fs4)
worker4 = SftpWorker(client4)
log4 = EventLog()
wire_worker(worker4, log4)
worker4.start()

tid_dl = worker4.queue_download("/home/small.txt", dl_dir, 200)
wait_until(lambda: log4.of_kind("done", tid_dl), timeout_ms=5000)
check("the download landed with the right content",
      open(os.path.join(dl_dir, "small.txt"), "rb").read() == b"x" * 200)
check("a successful download leaves no `.part` file", local_parts(dl_dir) == [],
      f"dir={os.listdir(dl_dir)}")

# A cancelled download must leave the EXISTING local file byte-identical.
SENTINEL = b"the previous local version\n"
with open(os.path.join(dl_dir, "big.bin"), "wb") as f:
    f.write(SENTINEL)
fs4.add_file("/home/big.bin", b"y" * (8 * 32768))
client4._chunk_delay = 0.02
tid_dl2 = worker4.queue_download("/home/big.bin", dl_dir, 8 * 32768)
wait_until(lambda: log4.of_kind("progress", tid_dl2), timeout_ms=5000)
worker4.cancel()
wait_until(lambda: log4.of_kind("cancelled", tid_dl2), timeout_ms=8000)
check("the cancelled download reported task_cancelled",
      bool(log4.of_kind("cancelled", tid_dl2)))
check("the local destination is BYTE-IDENTICAL after the cancelled download",
      open(os.path.join(dl_dir, "big.bin"), "rb").read() == SENTINEL,
      f"got={open(os.path.join(dl_dir, 'big.bin'), 'rb').read()[:40]!r}")
check("the cancelled download left no `.part` file", local_parts(dl_dir) == [],
      f"dir={os.listdir(dl_dir)}")

# A failing download (the source vanished) is not an error to the destination either.
tid_dl3 = worker4.queue_download("/home/gone.bin", dl_dir, 10)
wait_until(lambda: log4.of_kind("error", tid_dl3), timeout_ms=5000)
check("the download of a missing file → task_error", bool(log4.of_kind("error", tid_dl3)))
check("the failed download created nothing locally",
      not os.path.exists(os.path.join(dl_dir, "gone.bin")) and local_parts(dl_dir) == [])

worker4.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 5. The tab: the context menu (the test seam)
# ════════════════════════════════════════════════════════════
print("== 5. tab: the context menu ==")

fs5 = FakeSftpFS()
fs5.add_dir("/home")
fs5.add_dir("/home/sub")
fs5.add_file("/home/a.txt", b"alpha")
tab5, worker5, log5, _client5 = make_tab(fs5)
tab5._navigate("/home")
wait_until(lambda: item_by_name(tab5, "a.txt") is not None, timeout_ms=5000)

menu = tab5._build_context_menu(item_by_name(tab5, "a.txt"))
actions = [a for a in menu.actions() if not a.isSeparator()]
labels = [a.text() for a in actions]
expected = [i18n.t("sftp.op.new_folder"), i18n.t("sftp.op.rename"),
            i18n.t("sftp.op.delete"), i18n.t("sftp.op.copy_path"),
            i18n.t("sftp.refresh")]
check("the context menu carries the four operations + Refresh", labels == expected,
      f"labels={labels}")
check("on a real row Rename/Delete/Copy are enabled",
      all(a.isEnabled() for a in actions[:4]), f"got={[a.isEnabled() for a in actions]}")
check("New folder is always available (the current directory is the target)",
      actions[0].isEnabled())

menu_up = tab5._build_context_menu(tab5._up_item)
up_actions = [a for a in menu_up.actions() if not a.isSeparator()]
check("on the '..' row Rename/Delete/Copy are DISABLED",
      [a.isEnabled() for a in up_actions] == [True, False, False, False, True],
      f"got={[a.isEnabled() for a in up_actions]}")

menu_empty = tab5._build_context_menu(None)
empty_actions = [a for a in menu_empty.actions() if not a.isSeparator()]
check("on empty space only New folder / Refresh are enabled",
      [a.isEnabled() for a in empty_actions] == [True, False, False, False, True],
      f"got={[a.isEnabled() for a in empty_actions]}")

check("the tree is drag-enabled and drag-only",
      tab5.tree.dragEnabled() is True
      and tab5.tree.dragDropMode() == STAB.QTreeWidget.DragDropMode.DragOnly)
check("the tree carries the drag hint in the tooltip",
      tab5.tree.toolTip() == i18n.t("sftp.drag_hint"), f"got={tab5.tree.toolTip()!r}")

# The context menu of a file does NOT open the preview (the double-click gesture is
# untouched — the v1.3.1 viewer keeps working next to the v1.3.3.2 menu).
check("building the context menu does not open the viewer", tab5.viewer.isHidden())
tab5._on_item_double_clicked(item_by_name(tab5, "a.txt"), 0)
wait_until(lambda: not tab5.viewer.isHidden(), timeout_ms=5000)
check("the double-click preview still works after the context menu was added",
      tab5.viewer_text.toPlainText() == "alpha")
tab5.close_viewer()


# ════════════════════════════════════════════════════════════
# 6. The operations through the tab (the listing refresh included)
# ════════════════════════════════════════════════════════════
print("== 6. tab: New folder / Rename / Delete / Copy remote path ==")

msgs5 = []
tab5.message.connect(msgs5.append)

# ── New folder ──
_FakeInputDialog.SCRIPT = ["created_dir"]
tab5._op_new_folder()
wait_until(lambda: item_by_name(tab5, "created_dir") is not None, timeout_ms=5000)
check("New folder created the directory AND refreshed the listing",
      item_by_name(tab5, "created_dir") is not None and "/home/created_dir" in fs5.dirs)
check("the successful operation reported the done message",
      i18n.t("sftp.op.done", name="/home/created_dir") in msgs5, f"msgs={msgs5}")

# ── The name validation ──
msgs5.clear()
_FakeInputDialog.SCRIPT = ["bad/name"]
tab5._op_new_folder()
wait_until(lambda: msgs5, timeout_ms=2000)
check("a name with a path separator is refused with a translated hint",
      msgs5 == [i18n.t("sftp.op.invalid_name")], f"msgs={msgs5}")
_FakeInputDialog.SCRIPT = []          # cancelled dialog
msgs5.clear()
tab5._op_new_folder()
check("a cancelled dialog does nothing (no message, no task)",
      msgs5 == [] and "/home/bad" not in fs5.dirs)

# ── Rename ──
_FakeInputDialog.SCRIPT = ["renamed.txt"]
msgs5.clear()
tab5._op_rename(item_by_name(tab5, "a.txt"))
wait_until(lambda: item_by_name(tab5, "renamed.txt") is not None, timeout_ms=5000)
check("Rename changed the name on the 'server'",
      "/home/renamed.txt" in fs5.files and "/home/a.txt" not in fs5.files,
      f"files={sorted(fs5.files)}")
check("the listing shows the new name", item_by_name(tab5, "renamed.txt") is not None)
check("Rename kept the content", fs5.files.get("/home/renamed.txt") == b"alpha")

# ── Delete (with the confirmation) ──
_FakeMessageBox.CONFIRM = False
tab5._op_delete(item_by_name(tab5, "renamed.txt"))
app.processEvents()
check("a refused confirmation keeps the file",
      item_by_name(tab5, "renamed.txt") is not None)
_FakeMessageBox.CONFIRM = True
msgs5.clear()
tab5._op_delete(item_by_name(tab5, "renamed.txt"))
wait_until(lambda: item_by_name(tab5, "renamed.txt") is None, timeout_ms=5000)
check("a confirmed Delete removed the file and refreshed the listing",
      "/home/renamed.txt" not in fs5.files
      and item_by_name(tab5, "renamed.txt") is None)

# ── Delete a directory ──
tab5._op_delete(item_by_name(tab5, "created_dir"))
wait_until(lambda: item_by_name(tab5, "created_dir") is None, timeout_ms=5000)
check("Delete removes an empty directory", "/home/created_dir" not in fs5.dirs)

# ── Copy remote path ──
msgs5.clear()
tab5._op_copy_path(item_by_name(tab5, "sub"))
check("Copy remote path put the REMOTE path on the clipboard",
      QApplication.clipboard().text() == "/home/sub",
      f"got={QApplication.clipboard().text()!r}")
check("Copy remote path reported the translated hint",
      msgs5 == [i18n.t("sftp.op.path_copied")], f"msgs={msgs5}")

# ── A failing operation reports the error and does not break the tab ──
msgs5.clear()
_FakeInputDialog.SCRIPT = ["sub"]     # already exists → the server refuses
tab5._op_new_folder()
error_prefix = i18n.t("sftp.op.error", error="").strip()
wait_until(lambda: any(m.startswith(error_prefix) for m in msgs5), timeout_ms=5000)
check("a failing operation → the translated error message",
      any(m.startswith(error_prefix) for m in msgs5), f"msgs={msgs5}")
check("the failing operation refreshed nothing (the listing is untouched)",
      tab5.path_label.text() == "/home")
_FakeInputDialog.SCRIPT = ["after_failure"]
tab5._op_new_folder()
wait_until(lambda: item_by_name(tab5, "after_failure") is not None, timeout_ms=5000)
check("the NEXT operation still runs (the queue lives on)",
      item_by_name(tab5, "after_failure") is not None)

worker5.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 7. The overwrite conflict (ROADMAP task 2)
# ════════════════════════════════════════════════════════════
print("== 7. tab: the overwrite conflict ==")

OLD = {name: ("old-" + name).encode() for name in ("e1.txt", "e2.txt", "e3.txt")}


def fresh_conflict_tab():
    fs = FakeSftpFS()
    fs.add_dir("/home")
    for name, data in OLD.items():
        fs.add_file("/home/" + name, data)
    tab, worker, log, client = make_tab(fs)
    tab._navigate("/home")
    wait_until(lambda: item_by_name(tab, "e1.txt") is not None, timeout_ms=5000)
    return fs, tab, worker, log


def local_batch():
    return [make_local_text(n, ("new-" + n).encode()) for n in ("e1.txt", "e2.txt", "e3.txt")]


def uploaded(log, count):
    """Wait for `count` more uploads to finish (the listing task's done is not one)."""
    return lambda: len(upload_starts(log)) >= count


# ── (a) Overwrite + Apply to all over a batch of three files ──
fs7, tab7, worker7, log7 = fresh_conflict_tab()
_FakeMessageBox.SCRIPT = [("overwrite", True)]
_FakeMessageBox.DIALOGS = []
tab7._on_drop(local_batch(), "/home")
wait_until(lambda: len(upload_starts(log7)) >= 3, timeout_ms=8000)
wait_until(lambda: fs7.files.get("/home/e3.txt") == b"new-e3.txt", timeout_ms=8000)
check("Apply-to-all overwrote ALL three files",
      [fs7.files.get("/home/" + n) for n in OLD]
      == [b"new-e1.txt", b"new-e2.txt", b"new-e3.txt"],
      f"files={ {k: bytes(v) for k, v in fs7.files.items()} }")
check("Apply-to-all asked exactly ONE question",
      len(_FakeMessageBox.DIALOGS) == 1, f"dialogs={_FakeMessageBox.DIALOGS}")
title, text, buttons, apply_label = _FakeMessageBox.DIALOGS[0]
check("the dialog title is the i18n conflict title",
      title == i18n.t("sftp.conflict.title"), f"got={title!r}")
check("the dialog names the file and the target directory",
      text == i18n.t("sftp.conflict.message", name="e1.txt", target="/home"),
      f"got={text!r}")
check("the dialog offers the three i18n buttons + the Apply-to-all checkbox",
      buttons == sorted([i18n.t("sftp.conflict.overwrite"), i18n.t("sftp.conflict.skip"),
                         i18n.t("sftp.conflict.rename")])
      and apply_label == i18n.t("sftp.conflict.apply_all"),
      f"buttons={buttons} apply={apply_label!r}")
worker7.shutdown(wait_ms=2000)

# ── (b) Skip + Apply to all: nothing is destroyed ──
fs8, tab8, worker8, log8 = fresh_conflict_tab()
_FakeMessageBox.SCRIPT = [("skip", True)]
_FakeMessageBox.DIALOGS = []
tab8._on_drop(local_batch(), "/home")
app.processEvents()
wait_until(lambda: len(_FakeMessageBox.DIALOGS) >= 1, timeout_ms=3000)
time.sleep(0.2)
app.processEvents()
check("Skip + Apply-to-all kept EVERY destination byte-identical",
      all(fs8.files.get("/home/" + n) == OLD[n] for n in OLD),
      f"files={ {k: bytes(v) for k, v in fs8.files.items()} }")
check("Skip+Apply-to-all queued no upload at all", not upload_starts(log8),
      f"starts={upload_starts(log8)}")
check("Skip+Apply-to-all asked exactly one question", len(_FakeMessageBox.DIALOGS) == 1)
worker8.shutdown(wait_ms=2000)

# ── (c) A cancelled dialog = skip (and the next file gets its own question) ──
fs9, tab9, worker9, log9 = fresh_conflict_tab()
_FakeMessageBox.SCRIPT = [(None, False), ("overwrite", False)]
_FakeMessageBox.DIALOGS = []
tab9._on_drop([make_local_text("e1.txt", b"new-e1.txt"),
               make_local_text("e2.txt", b"new-e2.txt")], "/home")
wait_until(lambda: len(upload_starts(log9)) >= 1, timeout_ms=5000)
wait_until(lambda: fs9.files.get("/home/e2.txt") == b"new-e2.txt", timeout_ms=5000)
check("a CANCELLED dialog skipped that file (the destination is untouched)",
      fs9.files.get("/home/e1.txt") == OLD["e1.txt"],
      f"got={bytes(fs9.files.get('/home/e1.txt', b''))!r}")
check("the file AFTER a cancelled dialog was still uploaded",
      fs9.files.get("/home/e2.txt") == b"new-e2.txt")
check("the cancelled dialog did not cancel the batch (two questions were asked)",
      len(_FakeMessageBox.DIALOGS) == 2, f"dialogs={len(_FakeMessageBox.DIALOGS)}")
worker9.shutdown(wait_ms=2000)

# ── (d) Rename: the destination keeps its name, the copy gets a new one ──
fs10, tab10, worker10, log10 = fresh_conflict_tab()
_FakeMessageBox.SCRIPT = [("rename", False)]
_FakeMessageBox.DIALOGS = []
_FakeInputDialog.SCRIPT = ["e1-copy.txt"]
tab10._on_drop([make_local_text("e1.txt", b"new-e1.txt")], "/home")
wait_until(lambda: fs10.files.get("/home/e1-copy.txt") == b"new-e1.txt", timeout_ms=5000)
check("Rename uploaded under the NEW name", fs10.files.get("/home/e1-copy.txt") == b"new-e1.txt")
check("Rename left the existing file untouched",
      fs10.files.get("/home/e1.txt") == OLD["e1.txt"])
check("Rename asked a name (the QInputDialog path)", not _FakeInputDialog.SCRIPT)
_FakeInputDialog.SCRIPT = []
worker10.shutdown(wait_ms=2000)

# ── (e) The download direction: the same dialog, the local existence check ──
dl_dir2 = os.path.join(WORK, "dl_conflict")
os.makedirs(dl_dir2, exist_ok=True)
with open(os.path.join(dl_dir2, "e1.txt"), "wb") as f:
    f.write(b"local-old")
fs11 = FakeSftpFS()
fs11.add_dir("/home")
fs11.add_file("/home/e1.txt", b"remote-new")
fs11.add_file("/home/e2.txt", b"remote-second")
tab11, worker11, log11, _c11 = make_tab(fs11)
tab11._navigate("/home")
wait_until(lambda: item_by_name(tab11, "e1.txt") is not None, timeout_ms=5000)
_FakeMessageBox.SCRIPT = [("overwrite", False)]
_FakeMessageBox.DIALOGS = []
_FakeFileDialog.DIR = dl_dir2
tab11.tree.clearSelection()
item_by_name(tab11, "e1.txt").setSelected(True)
tab11.btn_download.click()
wait_until(lambda: open(os.path.join(dl_dir2, "e1.txt"), "rb").read() == b"remote-new",
           timeout_ms=5000)
check("a download conflict asks the same question and overwrites on request",
      open(os.path.join(dl_dir2, "e1.txt"), "rb").read() == b"remote-new")
check("the download conflict dialog was shown once", len(_FakeMessageBox.DIALOGS) == 1)

# A skip keeps the local file; a NO-conflict file is downloaded without a question.
_FakeMessageBox.SCRIPT = [("skip", False)]
_FakeMessageBox.DIALOGS = []
tab11.tree.clearSelection()
item_by_name(tab11, "e1.txt").setSelected(True)
item_by_name(tab11, "e2.txt").setSelected(True)
tab11.btn_download.click()
wait_until(lambda: os.path.exists(os.path.join(dl_dir2, "e2.txt")), timeout_ms=5000)
check("Skip kept the local file as it was",
      open(os.path.join(dl_dir2, "e1.txt"), "rb").read() == b"remote-new")
check("the non-conflicting file of the same batch was downloaded without a question",
      open(os.path.join(dl_dir2, "e2.txt"), "rb").read() == b"remote-second")
check("only the conflicting file asked a question", len(_FakeMessageBox.DIALOGS) == 1,
      f"dialogs={len(_FakeMessageBox.DIALOGS)}")
check("no `.part` file is left in the local directory", local_parts(dl_dir2) == [],
      f"dir={os.listdir(dl_dir2)}")
worker11.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 8. A drop onto a DIRECTORY ROW (ROADMAP task 4)
# ════════════════════════════════════════════════════════════
print("== 8. tab: the drop target is the directory under the cursor ==")

fs12 = FakeSftpFS()
fs12.add_dir("/home")
fs12.add_dir("/home/sub")
fs12.add_file("/home/a.txt", b"a")
tab12, worker12, log12, _c12 = make_tab(fs12)
tab12.resize(900, 600)
tab12.show()
app.processEvents()
tab12._navigate("/home")
wait_until(lambda: item_by_name(tab12, "sub") is not None, timeout_ms=5000)
app.processEvents()

row = tab12.tree.visualItemRect(item_by_name(tab12, "sub"))
check("the directory row has a real geometry (the drop can be aimed at it)",
      row.height() > 0 and row.width() > 0, f"row={row}")

mime_row = mime_with(make_local_text("into_sub.txt", b"sub-content"))
ev_row = drop_event(mime_row, row.center())
consumed = tab12.eventFilter(tab12.tree.viewport(), ev_row)
check("the drop on the tree viewport is consumed by the tab", consumed is True)
wait_until(lambda: fs12.files.get("/home/sub/into_sub.txt") == b"sub-content",
           timeout_ms=5000)
check("the drop on the DIRECTORY ROW uploaded into THAT directory",
      fs12.files.get("/home/sub/into_sub.txt") == b"sub-content",
      f"files={ {k: bytes(v) for k, v in fs12.files.items()} }")
check("the file did NOT land in the current directory",
      "/home/into_sub.txt" not in fs12.files)

# A drop on empty space (below the rows) keeps the current directory.
mime_body = mime_with(make_local_text("into_home.txt", b"home-content"))
ev_body = drop_event(mime_body, QPoint(10, max(row.bottom() + 40, 200)))
tab12.eventFilter(tab12.tree.viewport(), ev_body)
wait_until(lambda: fs12.files.get("/home/into_home.txt") == b"home-content",
           timeout_ms=5000)
check("a drop on empty space keeps the CURRENT directory",
      fs12.files.get("/home/into_home.txt") == b"home-content")

# A drop on a FILE row keeps the current directory as well.
row_file = tab12.tree.visualItemRect(item_by_name(tab12, "a.txt"))
mime_file = mime_with(make_local_text("via_file_row.txt", b"file-row"))
ev_file = drop_event(mime_file, row_file.center())
tab12.eventFilter(tab12.tree.viewport(), ev_file)
wait_until(lambda: fs12.files.get("/home/via_file_row.txt") == b"file-row",
           timeout_ms=5000)
check("a drop on a FILE row goes into the current directory",
      fs12.files.get("/home/via_file_row.txt") == b"file-row")

# The PRODUCTION delivery path: with DragOnly the tree's viewport no longer accepts
# drops, so Qt hands them to the TAB itself — the point is then in TAB coordinates
# and must be mapped back into the tree to find the row.
tab_pos = tab12.tree.viewport().mapTo(tab12, row.center())
mime_tab = mime_with(make_local_text("via_tab_coords.bin", b"tab"))
ev_tab = drop_event(mime_tab, tab_pos)
check("the drop delivered to the TAB (not the viewport) is consumed",
      tab12.eventFilter(tab12, ev_tab) is True)
wait_until(lambda: fs12.files.get("/home/sub/via_tab_coords.bin") is not None, timeout_ms=5000)
check("a drop delivered to the tab still resolves the directory UNDER THE CURSOR",
      fs12.files.get("/home/sub/via_tab_coords.bin") == b"tab",
      f"files={ {k: bytes(v) for k, v in fs12.files.items()} }")

# The pre-flight listing: dropping into a directory that is NOT on the screen.
fs12.add_dir("/other")
tab12._relist("/")            # the tab now shows "/" — /other is not in the tree
wait_until(lambda: item_by_name(tab12, "other") is not None, timeout_ms=5000)
tab12._navigate("/home")      # /home is the current dir, the target is /other
wait_until(lambda: item_by_name(tab12, "sub") is not None, timeout_ms=5000)
msgs12 = []
tab12.message.connect(msgs12.append)
tab12._on_drop([make_local_text("preflight.txt", b"pf")], "/other")
wait_until(lambda: fs12.files.get("/other/preflight.txt") == b"pf", timeout_ms=5000)
check("a drop into a directory that is NOT on the screen lands there (a pre-flight listing)",
      fs12.files.get("/other/preflight.txt") == b"pf",
      f"files={ {k: bytes(v) for k, v in fs12.files.items()} }")
check("the deferred drop still reports the drop_queued hint",
      i18n.t("sftp.drop_queued", count=1, dir="/other") in msgs12, f"msgs={msgs12}")

worker12.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 9. Drag-out as text (ROADMAP task 5)
# ════════════════════════════════════════════════════════════
print("== 9. tab: drag-out publishes the remote path ==")

fs13 = FakeSftpFS()
fs13.add_dir("/home")
fs13.add_dir("/home/sub")
fs13.add_file("/home/drag.txt", b"d")
tab13, worker13, _log13, _c13 = make_tab(fs13)
tab13._navigate("/home")
wait_until(lambda: item_by_name(tab13, "drag.txt") is not None, timeout_ms=5000)

mime = tab13.tree.drag_mime(item_by_name(tab13, "drag.txt"))
check("the drag mime exists and carries TEXT", mime is not None and mime.hasText())
check("the drag mime carries the REMOTE PATH as text/plain",
      mime.text() == "/home/drag.txt", f"got={mime.text()!r}")
check("the mime carries no URLs (the file itself is not transferred)",
      not mime.hasUrls())
check("a DIRECTORY row carries its path too",
      tab13.tree.drag_mime(item_by_name(tab13, "sub")).text() == "/home/sub")
check("the '..' row carries the parent directory it points at",
      tab13.tree.drag_mime(tab13._up_item).text() == "/")
check("no row → no mime", tab13.tree.drag_mime(None) is None)

worker13.shutdown(wait_ms=2000)

STAB.QMessageBox, STAB.QInputDialog, STAB.QFileDialog = _SAVED


# ════════════════════════════════════════════════════════════
# 10. i18n + the release state
# ════════════════════════════════════════════════════════════
print("== 10. i18n: the new sftp keys x4 + the release state ==")

NEW_KEYS = [
    "sftp.op.new_folder", "sftp.op.rename", "sftp.op.delete",
    "sftp.op.delete_confirm", "sftp.op.copy_path", "sftp.op.path_copied",
    "sftp.op.error", "sftp.op.name_prompt", "sftp.op.invalid_name",
    "sftp.op.done",
    "sftp.conflict.title", "sftp.conflict.message", "sftp.conflict.overwrite",
    "sftp.conflict.skip", "sftp.conflict.rename", "sftp.conflict.apply_all",
    "sftp.drag_hint",
]
check("exactly 17 new keys are introduced by v1.3.3.2", len(NEW_KEYS) == 17)

for code in i18n_lang_codes(ROOT):
    i18n.set_language(code)
    missing = [k for k in NEW_KEYS if i18n.t(k) == k or not i18n.t(k).strip()]
    check(f"{code}: all the 17 new keys are translated (not empty, not the raw key)",
          not missing, f"missing={missing}")
    formatted = i18n.t("sftp.conflict.message", name="x.txt", target="/tmp")
    check(f"{code}: the conflict message substitutes its placeholders",
          "{name}" not in formatted and "{target}" not in formatted
          and "x.txt" in formatted and "/tmp" in formatted, f"got={formatted!r}")

i18n.set_language("en")
check_i18n_parity(load_i18n_langs(ROOT))

check_release_state(ROOT)
finish()
