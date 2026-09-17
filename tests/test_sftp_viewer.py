# -*- coding: utf-8 -*-
"""v1.3.1 — File viewer in the SFTP tab (text ≤ 1 MB over SFTP, ROADMAP v1.3.1).

The release theme: the read-only preview inside the existing SFTP tab (stage 3 of the
file chain; stage 4 "editing" is rejected). Everything is checked WITHOUT the network:
the fake in-memory SFTP of tests/_fakes.py, extended locally by a client that journals
open() calls TOGETHER WITH THE THREAD they happened on (the acceptance requires that the
reading happens on the worker thread — never on the GUI thread).

The sections:
  1. The worker's "read" task: a text file ≤ 1 MB → read_ready with the exact bytes,
     the progress signals in order (monotonically growing, the last == the size),
     task_done after read_ready.
  2. Refusals: a file over MAX_READ_BYTES with a KNOWN size (not opened at all),
     an unknown size (the guard trips mid-read), a known-binary extension (not
     opened), a null byte in the first chunk — all as task_error with the machine
     codes; the queue survives them.
  3. The pure helpers: classify_extension (text/binary/unknown + the lists),
     decode_text (UTF-8, the BOM, the Latin-1 fallback).
  4. The tab offscreen: a double click on a file → a "read" task of the worker queue
     (opened on the worker thread, not the GUI thread) → the preview panel [tree |
     viewer] with the content and the header (path + size); another file replaces the
     content; × hides it; a repeated double click reopens it; a directory still
     navigates; two rapid double clicks end on the LAST file (the staleness filter).
     v1.3.3.2: the NEW context menu of the file operations does not shadow the
     double-click preview (it opens no panel and queues no read).
  5. The refusals and the "no preview" markers in the listing: the translated
     messages, no panel, nothing opened — and the row marks (v1.3.1.1): the pure
     helper preview_block_reason (a session fact → the certain size → the extension
     guess), the recoloured file glyph + the tooltip of a marked row, a directory
     never marked, the mark learned from a REAL refusal (a null byte inside a
     .txt — invisible to the extension), the mark surviving a re-listing and the
     facts dropped with the transport.
  6. Encodings: the Latin-1 fallback + the note in the header; a UTF-8 BOM is stripped.
  7. Teardown: page.shutdown() closes the preview (ROADMAP task 4) + set_worker(None).
  8. i18n (7 sftp.viewer.* keys × en/ru/zh, parity 446 → 453) + the release state.

Run:  python tests/test_sftp_viewer.py   (from the project root) or python tests/run_all.py
"""
import os
import sys
import threading

from _common import bootstrap, check, finish, wait_until, load_i18n_langs, check_i18n_parity, check_release_state

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

import i18n
import modules.sftp_tab as STAB
from modules.sftp_worker import (
    SftpWorker, MAX_READ_BYTES, KIND_READ, TEXT_EXTENSIONS, BINARY_EXTENSIONS,
    READ_ERROR_BINARY, READ_ERROR_TOO_LARGE, classify_extension,
)
from modules.sftp_tab import SftpTab, decode_text, format_size, preview_block_reason
from ui import theme   # v1.3.1.1: the "no preview" marker colour (no literals in code)

# The fake in-memory FS + the fake SFTPClient (no network) — the shared stubs _fakes.py
from _fakes import FakeSftpFS, FakeSftpClient, EventLog, wire_worker

MAIN_THREAD_IDENT = threading.main_thread().ident


class RecordingSftpClient(FakeSftpClient):
    """FakeSftpClient + the journal of open() calls: WHICH file and ON WHICH THREAD.

    The v1.3.1 acceptance ("reading ONLY via the worker queue, never in the main
    thread") is verified with it: every open() of a read task must carry the worker
    thread's ident, never the GUI/main thread's one.
    """

    def __init__(self, fs, chunk_delay=0.0):
        super().__init__(fs, chunk_delay)
        self.opens = []          # [(path, thread_ident), …]

    def open(self, path, mode="r"):
        self.opens.append((path, threading.current_thread().ident))
        return super().open(path, mode)

    def opened_paths(self):
        return [p for p, _tid in self.opens]


def item_by_name(tab, name):
    """The row of the listing by the visible name (None — not there yet)."""
    for i in range(tab.tree.topLevelItemCount()):
        it = tab.tree.topLevelItem(i)
        if it.text(0) == name:
            return it
    return None


def bin_path_opened(client, path):
    """Was the file opened at all (on any thread)?"""
    return path in client.opened_paths()


def icon_colors(icon):
    """The set of colours painted by a 16×16 icon (the icons are compared by their
    PIXELS: QIcon.cacheKey() is not stable — the style builds a fresh QIcon on
    every standardIcon() call, verified by a probe)."""
    img = icon.pixmap(16, 16).toImage()
    return {img.pixelColor(x, y).name() for x in range(16) for y in range(16)}


def icon_blocked(icon):
    """Does the icon carry the theme's "no preview" tone (the recoloured glyph)?"""
    return theme.SFTP_PREVIEW_BLOCKED.lower() in icon_colors(icon)


def make_fs():
    """The shared fake FS: text/binary/oversized/encoding samples (all under /home)."""
    fs = FakeSftpFS()
    fs.add_dir("/home")
    fs.add_dir("/home/sub")
    fs.add_file("/home/a.txt", b"alpha\nbeta\n")
    fs.add_file("/home/b.log", b"second file\n")
    fs.add_file("/home/sub/inside.txt", b"in\n")
    fs.add_file("/home/latin.txt", "caf\u00e9\n".encode("latin-1"))
    fs.add_file("/home/bom.txt", b"\xef\xbb\xbfbom text\n")
    fs.add_file("/home/sneaky.txt", b"text\x00binary")     # .txt, but a null byte
    fs.add_file("/home/image.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    fs.add_file("/home/big.log", b"x" * (MAX_READ_BYTES + 5))
    return fs


# ════════════════════════════════════════════════════════════
# 1. Worker: the "read" task — the content, the progress order
# ════════════════════════════════════════════════════════════
print("== 1. worker: read task — content + progress in order ==")

fs1 = make_fs()
# A text payload of 4 chunks (3 × 32 KB + a tail): the progress is observable.
payload = b"line of text\n" * 8400 + b"tail marker\n"
fs1.add_file("/home/plain.txt", payload)
client1 = RecordingSftpClient(fs1, chunk_delay=0.005)
worker1 = SftpWorker(client1)
log1 = EventLog()
wire_worker(worker1, log1)
worker1.start()

tid_read = worker1.queue_read("/home/plain.txt", len(payload))
check("the queue_read returned a task id", tid_read == 1, f"got={tid_read}")

wait_until(lambda: log1.of_kind("read", tid_read), timeout_ms=8000)
app.processEvents()
read_ev = log1.of_kind("read", tid_read)
check("read_ready arrived", bool(read_ev), f"events={log1.events}")
check("read_ready carries the requested path", read_ev[0][2] == "/home/plain.txt",
      f"got={read_ev[0][2]!r}")
check("read_ready carries the exact bytes of the file", read_ev[0][3] == payload,
      f"len={len(read_ev[0][3])} expected={len(payload)}")

idx = [e for e in log1.events if len(e) > 1 and e[1] == tid_read]
kinds = [e[0] for e in idx]
check("the event order: started → progress* → read → done",
      kinds[0] == "started" and kinds[-1] == "done" and kinds[-2] == "read"
      and all(k == "progress" for k in kinds[1:-2]),
      f"kinds={kinds}")

prog = [e[2] for e in log1.of_kind("progress", tid_read)]
check("the progress grows monotonically", prog and all(x <= y for x, y in zip(prog, prog[1:])),
      f"prog={prog}")
check("the progress is chunked by 32 KB (4 chunks for this payload)",
      len(prog) == 4 and prog[0] == 32768, f"prog={prog}")
check("the final progress == the total (the size from the listing)", prog[-1] == len(payload),
      f"last={prog[-1]} total={len(payload)}")
check("the task_done detail is the remote path",
      log1.of_kind("done", tid_read)[0][2] == "/home/plain.txt")
check("the file was opened on the WORKER thread (never on the GUI thread)",
      bool(client1.opens) and all(tid != MAIN_THREAD_IDENT for _p, tid in client1.opens),
      f"opens={client1.opens}")

# A second read: the queue is FIFO and STILL alive after the first one.
tid_read2 = worker1.queue_read("/home/b.log", len(fs1.files["/home/b.log"]))
wait_until(lambda: log1.of_kind("read", tid_read2), timeout_ms=5000)
check("a second read on the same worker finished",
      log1.of_kind("read", tid_read2)[0][3] == b"second file\n")

worker1.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 2. Worker: refusals — the limit and the binary screen; the queue survives
# ════════════════════════════════════════════════════════════
print("== 2. worker: limit + binary refusals ==")

fs2 = make_fs()
client2 = RecordingSftpClient(fs2)
worker2 = SftpWorker(client2)
log2 = EventLog()
wire_worker(worker2, log2)
worker2.start()

# A known size over the limit: refused BEFORE opening the file at all.
tid_big = worker2.queue_read("/home/big.log", MAX_READ_BYTES + 5)
wait_until(lambda: log2.of_kind("error", tid_big), timeout_ms=5000)
err = log2.of_kind("error", tid_big)[0]
check("a file over 1 MB → task_error with the TOO_LARGE code",
      err[2] == KIND_READ and err[3] == READ_ERROR_TOO_LARGE, f"got={err}")
check("the oversized file was NOT opened (not read at all)",
      "/home/big.log" not in client2.opened_paths(), f"opens={client2.opened_paths()}")
check("no read_ready for the refused file", not log2.of_kind("read", tid_big))
check("no progress for the refused file (a size refusal happens before the first chunk)",
      not log2.of_kind("progress", tid_big))

# An UNKNOWN size (0 from the listing): the guard trips while reading.
tid_unknown = worker2.queue_read("/home/big.log", 0)
wait_until(lambda: log2.of_kind("error", tid_unknown), timeout_ms=10000)
err_unknown = log2.of_kind("error", tid_unknown)[0]
check("an unknown size over the limit → the same TOO_LARGE code",
      err_unknown[3] == READ_ERROR_TOO_LARGE, f"got={err_unknown}")
check("no read_ready for the unknown-size refusal", not log2.of_kind("read", tid_unknown))
prog_unknown = [e[2] for e in log2.of_kind("progress", tid_unknown)]
check("the guard tripped mid-read (that file WAS being read)",
      bin_path_opened(client2, "/home/big.log") and len(prog_unknown) >= 32,
      f"opens={client2.opened_paths()} chunks={len(prog_unknown)}")

# A known-binary extension: refused without opening.
tid_png = worker2.queue_read("/home/image.png", 24)
wait_until(lambda: log2.of_kind("error", tid_png), timeout_ms=5000)
check("a known-binary extension → the BINARY code",
      log2.of_kind("error", tid_png)[0][3] == READ_ERROR_BINARY)
check("the .png was NOT opened", "/home/image.png" not in client2.opened_paths())

# The null byte in the first chunk — the decisive check (the extension lied).
tid_null = worker2.queue_read("/home/sneaky.txt", 12)
wait_until(lambda: log2.of_kind("error", tid_null), timeout_ms=5000)
check("a null byte in the first chunk → the BINARY code",
      log2.of_kind("error", tid_null)[0][3] == READ_ERROR_BINARY)
check("nothing was published for the binary file", not log2.of_kind("read", tid_null))

# The queue does not die on a refusal.
tid_after = worker2.queue_read("/home/a.txt", 11)
wait_until(lambda: log2.of_kind("read", tid_after), timeout_ms=5000)
check("the queue survives the refusals (the next read works)",
      log2.of_kind("read", tid_after)[0][3] == b"alpha\nbeta\n")
tid_list = worker2.queue_list("/home")
wait_until(lambda: log2.of_kind("list", tid_list), timeout_ms=5000)
check("the listing works after the refusals (the worker queue)",
      bool(log2.of_kind("list", tid_list)))
worker2.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 3. The pure helpers: classify_extension + decode_text
# ════════════════════════════════════════════════════════════
print("== 3. helpers: classify_extension + decode_text ==")

check("classify_extension: the text whitelist",
      all(classify_extension("x" + e) == "text" for e in (".log", ".txt", ".conf", ".ini",
                                                          ".py", ".sh", ".json", ".yml", ".xml")),
      f"n={len(TEXT_EXTENSIONS)}")
check("classify_extension: the binary blacklist",
      all(classify_extension("x" + e) == "binary" for e in (".png", ".zip", ".exe", ".pdf", ".so")))
check("classify_extension: an extensionless file counts as text (README/Makefile)",
      classify_extension("README") == "text" and classify_extension("/etc/hosts") == "text")
check("classify_extension: an unknown extension is 'unknown' (read + the null-byte screen)",
      classify_extension("data.weird") == "unknown")
check("classify_extension: the case does not matter",
      classify_extension("A.TXT") == "text" and classify_extension("A.PNG") == "binary")
check("classify_extension: the lists are disjoint frozensets",
      isinstance(TEXT_EXTENSIONS, frozenset) and isinstance(BINARY_EXTENSIONS, frozenset)
      and not (TEXT_EXTENSIONS & BINARY_EXTENSIONS))

check("decode_text: plain UTF-8",
      decode_text("h\u00e9llo \u20ac\n".encode("utf-8")) == ("h\u00e9llo \u20ac\n", "utf-8"))
check("decode_text: an UTF-8 BOM is stripped (utf-8-sig)",
      decode_text(b"\xef\xbb\xbfhello") == ("hello", "utf-8"))
check("decode_text: a decode failure → the Latin-1 fallback + the encoding",
      decode_text("caf\u00e9\n".encode("latin-1")) == ("caf\u00e9\n", "latin-1"))
check("decode_text: Latin-1 never raises on arbitrary bytes",
      decode_text(b"\xff\xfe\x80")[1] == "latin-1" and len(decode_text(b"\xff\xfe\x80")[0]) == 3)
check("the limit constant is 1 MB", MAX_READ_BYTES == 1024 * 1024)
check("format_size(MAX_READ_BYTES) == '1.0 MB'", format_size(MAX_READ_BYTES) == "1.0 MB")


# ════════════════════════════════════════════════════════════
# 4. SftpTab: the preview panel (offscreen, no network)
# ════════════════════════════════════════════════════════════
print("== 4. sftp tab: the preview panel ==")

fs4 = make_fs()
client4 = RecordingSftpClient(fs4)
worker4 = SftpWorker(client4)
log4 = EventLog()
wire_worker(worker4, log4)
worker4.start()

tab = SftpTab()
msgs = []
tab.message.connect(msgs.append)
tab.set_worker(worker4)
wait_until(lambda: item_by_name(tab, "home") is not None, timeout_ms=5000)
tab._navigate("/home")
wait_until(lambda: item_by_name(tab, "a.txt") is not None, timeout_ms=5000)

check("the body is a QSplitter [tree | viewer]", tab.splitter.count() == 2
      and tab.splitter.widget(0) is tab.tree and tab.splitter.widget(1) is tab.viewer)
check("the panel starts hidden", tab.viewer.isHidden())
check("the viewer is read-only", tab.viewer_text.isReadOnly())
check("the viewer does not wrap long lines",
      tab.viewer_text.lineWrapMode() == STAB.QPlainTextEdit.LineWrapMode.NoWrap)
check("the viewer's font is monospace", tab.viewer_text.font().fixedPitch()
      or "mono" in tab.viewer_text.font().family().lower(),
      f"family={tab.viewer_text.font().family()!r}")
check("the close cross carries the i18n tooltip",
      tab.btn_viewer_close.toolTip() == i18n.t("sftp.viewer.close_tooltip"))

item_a = item_by_name(tab, "a.txt")
tab._on_item_double_clicked(item_a, 0)
check("the double click QUEUES a read task (the tab never reads the file itself)",
      list(tab._read_tasks.values()) == ["/home/a.txt"] and tab._last_read is not None,
      f"tasks={tab._read_tasks}")

wait_until(lambda: not tab.viewer.isHidden(), timeout_ms=5000)
check("the preview opened on a double click on a text file", not tab.viewer.isHidden())
check("the content is the file's content", tab.viewer_text.toPlainText() == "alpha\nbeta\n",
      f"got={tab.viewer_text.toPlainText()!r}")
check("the header line: path + size",
      tab.viewer_label.text() == i18n.t("sftp.viewer.header", path="/home/a.txt", size="11 B"),
      f"got={tab.viewer_label.text()!r}")
check("the read went through the worker queue (a 'read' task_started)",
      any(len(e) > 3 and e[0] == "started" and e[2] == KIND_READ and e[3] == "a.txt"
          for e in log4.events),
      f"events={[e[:4] for e in log4.events]}")
check("the file was opened on the WORKER thread, not on the GUI thread",
      bool(client4.opens) and all(tid != MAIN_THREAD_IDENT for _p, tid in client4.opens),
      f"opens={client4.opens}")
check("the bookkeeping is dropped after the answer",
      not tab._read_tasks and tab._last_read is None)

# Another file replaces the content of the same panel.
item_b = item_by_name(tab, "b.log")
tab._on_item_double_clicked(item_b, 0)
wait_until(lambda: tab.viewer_text.toPlainText() == "second file\n", timeout_ms=5000)
check("selecting another file REPLACES the content", tab.viewer_text.toPlainText() == "second file\n")
check("the header follows the new file",
      tab.viewer_label.text() == i18n.t("sftp.viewer.header", path="/home/b.log", size="12 B"),
      f"got={tab.viewer_label.text()!r}")

# × hides the panel; a repeated double click opens it again.
tab.btn_viewer_close.click()
check("× closes the panel and drops the content",
      tab.viewer.isHidden() and tab.viewer_text.toPlainText() == ""
      and tab.viewer_label.text() == "")
tab._on_item_double_clicked(item_a, 0)
wait_until(lambda: not tab.viewer.isHidden(), timeout_ms=5000)
check("a repeated double click reopens the panel with the content",
      tab.viewer_text.toPlainText() == "alpha\nbeta\n")

# Two rapid double clicks: the LAST file wins (the staleness filter).
tab._on_item_double_clicked(item_a, 0)
tab._on_item_double_clicked(item_b, 0)
wait_until(lambda: tab.viewer_text.toPlainText() == "second file\n", timeout_ms=5000)
check("two rapid double clicks end on the LAST selected file (the staleness filter)",
      tab.viewer_text.toPlainText() == "second file\n",
      f"got={tab.viewer_text.toPlainText()!r}")
check("no message was emitted by a successful read", not msgs, f"msgs={msgs}")

# The tree behaviour for directories is unchanged (navigation, not a preview).
opened_before = list(client4.opened_paths())
tab._on_item_double_clicked(item_by_name(tab, "sub"), 0)
wait_until(lambda: tab.path_label.text() == "/home/sub", timeout_ms=5000)
check("a double click on a directory still navigates", tab.path_label.text() == "/home/sub")
check("the navigation did not open any file", client4.opened_paths() == opened_before)
tab.go_up()
wait_until(lambda: tab.path_label.text() == "/home", timeout_ms=5000)

# ── v1.3.3.2: the file-operations CONTEXT MENU does not shadow the preview ──
# The menu is built by the seam without exec() (Qt gotcha: no modal dialogs offscreen)
# and must neither open the panel nor queue a read.
tab.close_viewer()
msgs.clear()
reads_before = len([e for e in log4.events if e[0] == "started" and e[2] == KIND_READ])
menu = tab._build_context_menu(item_by_name(tab, "a.txt"))
check("v1.3.3.2: the context menu of a file row is built without opening the viewer",
      menu is not None and tab.viewer.isHidden())
check("v1.3.3.2: building it queued no read task",
      len([e for e in log4.events if e[0] == "started" and e[2] == KIND_READ]) == reads_before
      and not tab._read_tasks, f"read_tasks={tab._read_tasks}")
check("v1.3.3.2: the menu carries the four file operations + Refresh",
      [a.text() for a in menu.actions() if not a.isSeparator()]
      == [i18n.t("sftp.op.new_folder"), i18n.t("sftp.op.rename"), i18n.t("sftp.op.delete"),
          i18n.t("sftp.op.copy_path"), i18n.t("sftp.refresh")],
      f"got={[a.text() for a in menu.actions() if not a.isSeparator()]}")
tab._on_item_double_clicked(item_by_name(tab, "a.txt"), 0)
wait_until(lambda: not tab.viewer.isHidden(), timeout_ms=5000)
check("v1.3.3.2: the double-click preview still works after the menu was built",
      tab.viewer_text.toPlainText() == "alpha\nbeta\n")
tab.close_viewer()


# ════════════════════════════════════════════════════════════
# 5. SftpTab: the "no preview" markers + the refusals themselves
# ════════════════════════════════════════════════════════════
print("== 5. sftp tab: markers + binary / too large messages ==")

tab.close_viewer()   # the panel of §4 is open — a refusal must not open it
msgs.clear()

# ── v1.3.1.1: the pure helper — the order "fact → size → extension" ──
check("the helper: an ordinary text file is not marked",
      preview_block_reason("/home/a.txt", 100) == ""
      and preview_block_reason("/home/README", 10) == "")
check("the helper: a known-binary extension is marked 'binary' (the case does not matter)",
      preview_block_reason("/home/image.png", 10) == READ_ERROR_BINARY
      and preview_block_reason("/home/A.PNG", 10) == READ_ERROR_BINARY)
check("the helper: a file over the limit is marked 'too_large'",
      preview_block_reason("/home/big.log", MAX_READ_BYTES + 1) == READ_ERROR_TOO_LARGE)
check("the helper: exactly the limit is NOT marked (1 MB is readable)",
      preview_block_reason("/home/big.log", MAX_READ_BYTES) == "")
check("the helper: a broken/absent size never marks a row",
      preview_block_reason("/home/a.txt", None) == ""
      and preview_block_reason("/home/a.txt", "?") == "")
check("the helper: a session FACT wins over the extension guess",
      preview_block_reason("/home/a.txt", 10, {"/home/a.txt": READ_ERROR_BINARY})
      == READ_ERROR_BINARY
      and preview_block_reason("/home/image.png", 10,
                               {"/home/image.png": READ_ERROR_TOO_LARGE})
      == READ_ERROR_TOO_LARGE)
check("the helper: an empty facts map matches the no-facts answer",
      preview_block_reason("/home/image.png", 10, {}) == READ_ERROR_BINARY)

# ── the marks of a FRESH listing: certain size + the extension guess ──
# The icons are compared by their PAINTED PIXELS, not by QIcon.cacheKey(): the
# style builds a fresh QIcon on every standardIcon() call, so cacheKeys are never
# equal — even for two takes of the same glyph (verified by a probe).
plain_icon = tab._file_icon()
mark_png = item_by_name(tab, "image.png")
mark_big = item_by_name(tab, "big.log")
mark_txt = item_by_name(tab, "a.txt")
mark_dir = item_by_name(tab, "sub")
check("the plain file glyph does not carry the marker colour (no false positives)",
      not icon_blocked(plain_icon))
check("the listing marks a known-binary file (the tooltip = the i18n 'binary' text)",
      mark_png.toolTip(0) == i18n.t("sftp.viewer.binary"), f"tip={mark_png.toolTip(0)!r}")
check("the listing marks a file over 1 MB (the tooltip = the i18n 'too large' text)",
      mark_big.toolTip(0) == i18n.t("sftp.viewer.too_large", limit=format_size(MAX_READ_BYTES)),
      f"tip={mark_big.toolTip(0)!r}")
check("a marked row carries a RE-COLOURED glyph (the theme's 'no preview' tone)",
      icon_blocked(mark_png.icon(0)) and icon_blocked(mark_big.icon(0))
      and theme.SFTP_PREVIEW_BLOCKED == theme.STATUS_WARN,
      f"colour={theme.SFTP_PREVIEW_BLOCKED}")
check("the marked glyph is built once (cached)",
      tab._blocked_icon() is tab._blocked_icon())
check("an ordinary text file carries no marker",
      mark_txt.toolTip(0) == "" and not icon_blocked(mark_txt.icon(0)))
check("a directory is never marked (the glyph stays the directory icon)",
      mark_dir.toolTip(0) == ""
      and icon_colors(mark_dir.icon(0)) == icon_colors(tab._dir_icon())
      and not icon_blocked(mark_dir.icon(0)))
check("the extension alone cannot see a null byte: sneaky.txt looks previewable",
      item_by_name(tab, "sneaky.txt").toolTip(0) == ""
      and not icon_blocked(item_by_name(tab, "sneaky.txt").icon(0)))

# An injected fact marks an existing row (the state is the same one a refusal sets).
tab._blocked["/home/a.txt"] = READ_ERROR_BINARY
tab._mark_row("/home/a.txt")
check("a session fact marks the row of the file",
      item_by_name(tab, "a.txt").toolTip(0) == i18n.t("sftp.viewer.binary")
      and icon_blocked(item_by_name(tab, "a.txt").icon(0)))
tab._blocked.pop("/home/a.txt", None)
tab._mark_row("/home/a.txt")
check("dropping the fact restores the plain row",
      item_by_name(tab, "a.txt").toolTip(0) == ""
      and not icon_blocked(item_by_name(tab, "a.txt").icon(0)))
marks_before = [item_by_name(tab, n).toolTip(0) for n in ("a.txt", "image.png")]
tab._mark_row("/home/not-in-the-listing")
check("marking a path that is not in the listing touches nothing",
      [item_by_name(tab, n).toolTip(0) for n in ("a.txt", "image.png")] == marks_before)

# ── the refusals through the real click path ──
tab._on_item_double_clicked(item_by_name(tab, "sneaky.txt"), 0)
wait_until(lambda: msgs, timeout_ms=5000)
check("a null byte in the first chunk → the i18n 'binary file' message",
      msgs == [i18n.t("sftp.viewer.binary")], f"msgs={msgs}")
check("the binary refusal showed NO panel", tab.viewer.isHidden())
check("the refusal MARKED the row of the lying extension (the worker's verdict)",
      item_by_name(tab, "sneaky.txt").toolTip(0) == i18n.t("sftp.viewer.binary")
      and icon_blocked(item_by_name(tab, "sneaky.txt").icon(0)))
check("the fact is kept for the session",
      tab._blocked.get("/home/sneaky.txt") == READ_ERROR_BINARY,
      f"blocked={tab._blocked}")

msgs.clear()
tab._on_item_double_clicked(item_by_name(tab, "image.png"), 0)
wait_until(lambda: msgs, timeout_ms=5000)
check("a known-binary extension → the same message",
      msgs == [i18n.t("sftp.viewer.binary")], f"msgs={msgs}")
check("the .png was not opened at all", "/home/image.png" not in client4.opened_paths())

msgs.clear()
tab._on_item_double_clicked(item_by_name(tab, "big.log"), 0)
wait_until(lambda: msgs, timeout_ms=5000)
check("a file over 1 MB → the i18n 'larger than the limit' message",
      msgs == [i18n.t("sftp.viewer.too_large", limit=format_size(MAX_READ_BYTES))],
      f"msgs={msgs}")
check("the oversized refusal showed NO panel", tab.viewer.isHidden())
check("the oversized file was not read", "/home/big.log" not in client4.opened_paths())

# The tab still works after the refusals (the listing is rebuilt) — and the marks
# of the refreshed listing are still there (the fact + the guess are recomputed).
msgs.clear()
tab.btn_refresh.click()
wait_until(lambda: item_by_name(tab, "a.txt") is not None, timeout_ms=5000)
check("the listing works after the refusals", item_by_name(tab, "a.txt") is not None)
check("a re-listing keeps the learned mark",
      item_by_name(tab, "sneaky.txt").toolTip(0) == i18n.t("sftp.viewer.binary")
      and icon_blocked(item_by_name(tab, "sneaky.txt").icon(0)))
check("a re-listing keeps the guessed marks",
      item_by_name(tab, "image.png").toolTip(0) == i18n.t("sftp.viewer.binary")
      and item_by_name(tab, "big.log").toolTip(0)
      == i18n.t("sftp.viewer.too_large", limit=format_size(MAX_READ_BYTES)))
check("a successful read leaves no mark behind (a.txt was previewed in §4)",
      item_by_name(tab, "a.txt").toolTip(0) == ""
      and tab._blocked.get("/home/a.txt") is None)

# A read error that is NOT a viewer code is passed through with the path — and it
# is NOT a previewability fact (the row must stay unmarked).
tab._read_tasks[999] = "/home/gone.txt"
tab._last_read = 999
msgs.clear()
tab._on_task_error(999, KIND_READ, "No such file")
check("an unknown read error → the i18n read_failed message with the name",
      msgs == [i18n.t("sftp.viewer.read_failed", name="gone.txt", error="No such file")],
      f"msgs={msgs}")
check("a real I/O error is not a previewability fact",
      "/home/gone.txt" not in tab._blocked)


# ════════════════════════════════════════════════════════════
# 6. Encodings: the Latin-1 fallback + the BOM
# ════════════════════════════════════════════════════════════
print("== 6. sftp tab: encodings ==")

msgs.clear()
tab._on_item_double_clicked(item_by_name(tab, "latin.txt"), 0)
wait_until(lambda: not tab.viewer.isHidden(), timeout_ms=5000)
check("the Latin-1 fallback decodes the content",
      tab.viewer_text.toPlainText() == "caf\u00e9\n", f"got={tab.viewer_text.toPlainText()!r}")
check("the header carries the encoding note",
      tab.viewer_label.text().endswith(
          i18n.t("sftp.viewer.encoding_note", encoding="latin-1")),
      f"got={tab.viewer_label.text()!r}")
check("the header still starts with the path + size",
      tab.viewer_label.text().startswith(
          i18n.t("sftp.viewer.header", path="/home/latin.txt", size="5 B")),
      f"got={tab.viewer_label.text()!r}")
check("viewer_encoding reports the fallback", tab.viewer_encoding == "latin-1")

tab._on_item_double_clicked(item_by_name(tab, "bom.txt"), 0)
wait_until(lambda: tab.viewer_text.toPlainText() == "bom text\n", timeout_ms=5000)
check("a UTF-8 BOM is stripped", tab.viewer_text.toPlainText() == "bom text\n",
      f"got={tab.viewer_text.toPlainText()!r}")
check("no encoding note for the valid UTF-8",
      tab.viewer_label.text() == i18n.t("sftp.viewer.header", path="/home/bom.txt", size="12 B"),
      f"got={tab.viewer_label.text()!r}")
check("viewer_encoding reports utf-8", tab.viewer_encoding == "utf-8")

worker4.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 7. Teardown: page.shutdown() / set_worker(None) close the preview
# ════════════════════════════════════════════════════════════
print("== 7. teardown (offscreen, the fake terminal window) ==")

import modules.ssh_terminal as ST
from models.server import ServerData

# The §7 harness — the shared stubs _fakes.py (as in test_sftp_tab.py)
from _fakes import FakeSSHThread as _FakeSSHThread, FakeSSHClient as _FakeSshClient

_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeSSHThread

win = None
try:
    fs7 = FakeSftpFS()
    fs7.add_dir("/etc")
    fs7.add_file("/etc/hosts", b"127.0.0.1 localhost\n")
    client7 = RecordingSftpClient(fs7)
    win = ST.SSHTerminalWindow(
        ServerData(id="viewer-7", alias="viewer7", host="10.99.0.1", user="root"),
        None, password="pw")
    win.resize(700, 500)
    win.terminal_thread.client = _FakeSshClient(client7)
    win.tabs.setCurrentIndex(1)
    wait_until(lambda: win._sftp_worker is not None and win.sftp_tab.tree.topLevelItemCount() >= 1,
               timeout_ms=5000)
    tab7 = win.sftp_tab
    tab7._navigate("/etc")
    wait_until(lambda: item_by_name(tab7, "hosts") is not None, timeout_ms=5000)
    tab7._on_item_double_clicked(item_by_name(tab7, "hosts"), 0)
    wait_until(lambda: not tab7.viewer.isHidden(), timeout_ms=5000)
    check("the window's 'Files' tab previews a file over the live transport",
          tab7.viewer_text.toPlainText() == "127.0.0.1 localhost\n",
          f"got={tab7.viewer_text.toPlainText()!r}")

    page = win.page
    page.shutdown()
    check("page.shutdown() closes the preview together with the session (ROADMAP task 4)",
          tab7.viewer.isHidden() and tab7.viewer_text.toPlainText() == "")
    check("shutdown() stays idempotent (a repeated call is a no-op)",
          page.shutdown() is None)

    tab7._show_viewer("/etc/hosts", 21, "127.0.0.1 localhost\n")
    check("the panel can be shown again after the teardown of a dead session's preview",
          not tab7.viewer.isHidden())
    # v1.3.1.1: the previewability facts belong to the transport that was read —
    # a new connection (another server may answer on the same paths) starts clean.
    tab7._blocked["/etc/hosts"] = READ_ERROR_BINARY
    tab7.set_worker(None)
    check("the worker death (set_worker(None)) closes the preview",
          tab7.viewer.isHidden() and tab7.viewer_text.toPlainText() == "")
    check("set_worker(None) keeps the 'waiting for connection' state",
          tab7.path_label.text() == i18n.t("sftp.waiting_connection"))
    check("the learned preview facts are dropped together with the transport",
          tab7._blocked == {}, f"blocked={tab7._blocked}")
finally:
    if win is not None:
        try:
            win.close()
            app.processEvents()
        except Exception:  # noqa: BLE001 — the teardown must not mask the checks
            pass
    ST.SSHTerminalThread = _orig_thread_cls


# ════════════════════════════════════════════════════════════
# 8. i18n + the release state
# ════════════════════════════════════════════════════════════
print("== 8. i18n: sftp.viewer.* keys x3, parity 453 ==")

VIEWER_KEYS = [
    "sftp.viewer.header", "sftp.viewer.close_tooltip", "sftp.viewer.reading",
    "sftp.viewer.binary", "sftp.viewer.too_large", "sftp.viewer.encoding_note",
    "sftp.viewer.read_failed",
]
check("exactly 7 sftp.viewer.* keys are used in the code", len(VIEWER_KEYS) == 7)

for code in ("en", "ru", "zh"):
    i18n.set_language(code)
    missing = [k for k in VIEWER_KEYS if i18n.t(k) == k or not i18n.t(k).strip()]
    check(f"{code}: all the 7 sftp.viewer.* keys are translated (not empty, not the raw ones)",
          not missing, f"missing={missing}")

i18n.set_language("en")  # the default for cleanliness
check_i18n_parity(load_i18n_langs(ROOT))

check_release_state(ROOT)

finish()
