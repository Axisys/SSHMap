# -*- coding: utf-8 -*-
"""v1.3.1 — File viewer in the SFTP tab (text ≤ 1 MB over SFTP, ROADMAP v1.3.1).

The release theme: the read-only preview inside the existing SFTP tab (stage 3 of the file chain; stage
4 "editing" is rejected). Everything is checked WITHOUT the network — the fake in-memory SFTP of
tests/_fakes.py, extended by a client that journals `open()` calls with the THREAD they ran on.
§1 the worker's "read" task and its progress order; §2 the refusals (over MAX_READ_BYTES, an unknown
size, a binary extension, a null byte) and the queue surviving them; §3 `classify_extension` / `decode_text`;
§4–§5 the tab offscreen, its staleness filter and the markers; §6–§9 the encodings, the teardown, the
reader's encoding CHOICE and i18n."""
import os
import sys
import threading

from _common import (bootstrap, check, finish, wait_until, load_i18n_langs, check_i18n_parity,
                     check_release_state, read_cfg, write_cfg)

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

import i18n
import modules.sftp_tab as STAB
from modules.sftp_worker import (
    SftpWorker, MAX_READ_BYTES, KIND_READ, TEXT_EXTENSIONS, BINARY_EXTENSIONS,
    READ_ERROR_BINARY, READ_ERROR_TOO_LARGE, classify_extension,
)
from modules.sftp_tab import (SftpTab, decode_text, format_size, preview_block_reason,
                              read_was_truncated)
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

# N46: a read CUT at the ceiling must not be decoded as another encoding. The probe: the largest
# prefix of a Cyrillic file whose UTF-8 decode fails — the byte-exact cut the workers make.
_CYR = ("\u0421\u0435\u0440\u0432\u0435\u0440: \u043f\u0440\u043e\u0434\u0430\u043a\u0448\u043d\n" * 4)
_CYR_BUF = _CYR.encode("utf-8")
_CYR_CUT = 0
for _n in range(len(_CYR_BUF), 0, -1):
    try:
        _CYR_BUF[:_n].decode("utf-8-sig")
    except UnicodeDecodeError:
        _CYR_CUT = _n
        break
_CYR_HEAD = _CYR_BUF[:_CYR_CUT]
_CYR_INTACT = _CYR[:len(_CYR_HEAD.decode("utf-8", errors="ignore"))]
check("decode_text: a buffer cut MID-character answers latin-1 without the flag (the N46 defect)",
      _CYR_CUT and _CYR_HEAD[-1] >= 0xC0 and decode_text(_CYR_HEAD)[1] == "latin-1")
check("decode_text: ...and `truncated=True` holds the incomplete tail back and stays UTF-8",
      decode_text(_CYR_HEAD, truncated=True) == (_CYR_INTACT, "utf-8"),
      decode_text(_CYR_HEAD, truncated=True)[1])
_CJK_BUF = "\u65e5\u672c\u8a9e\u306e\u30c6\u30ad\u30b9\u30c8".encode("utf-8")
check("decode_text: a 3-byte character cut the same way is handled by the same rule",
      decode_text(_CJK_BUF[:-1], truncated=True) == (
          _CJK_BUF[:-1].decode("utf-8", errors="ignore"), "utf-8"))
check("decode_text: a COMPLETE Latin-1 file keeps its last character (the §G counter-case)",
      decode_text(b"caf\xe9") == ("caf\xe9", "latin-1")
      and decode_text(b"caf\xe9", truncated=True)[0] == "caf")
check("decode_text: a genuinely invalid byte still raises and still falls back",
      decode_text(_CYR_HEAD + b"\xff\xfe", truncated=True)[1] == "latin-1"
      and decode_text(b"\xff\xfe", truncated=True)[1] == "latin-1")
check("read_was_truncated: the listing's size wins, the ceiling is the fallback",
      read_was_truncated(5, 1024, 9) is True and read_was_truncated(9, 1024, 9) is False
      and read_was_truncated(1024, 1024, 0) is True and read_was_truncated(10, 1024, 0) is False)
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
check("v1.3.3.2: the menu carries the four file operations + the Send-to submenu + Refresh",
      [a.text() for a in menu.actions() if not a.isSeparator()]
      == [i18n.t("sftp.op.new_folder"), i18n.t("sftp.op.rename"), i18n.t("sftp.op.delete"),
          i18n.t("sftp.op.copy_path"), i18n.t("sftp.send.menu"), i18n.t("sftp.refresh")],
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
check("the helper: v1.7.5 — the SIZE is no longer a reason: the cap TRUNCATES, never refuses",
      preview_block_reason("/home/big.log", MAX_READ_BYTES + 1) == ""
      and preview_block_reason("/home/big.log", MAX_READ_BYTES * 4096) == "")
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
check("v1.7.5: a file over the cap carries NO marker (its preview is truncated, not refused)",
      mark_big.toolTip(0) == "" and not icon_blocked(mark_big.icon(0)),
      f"tip={mark_big.toolTip(0)!r}")
check("a marked row carries a RE-COLOURED glyph (the theme's 'no preview' tone)",
      icon_blocked(mark_png.icon(0))
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
wait_until(lambda: not tab.viewer.isHidden(), timeout_ms=10000)
check("v1.7.5: a file over the cap OPENS — truncated at the ceiling, never refused",
      tab.viewer.isHidden() is False
      and len(tab.viewer_text.toPlainText()) == MAX_READ_BYTES
      and not msgs, f"msgs={msgs} len={len(tab.viewer_text.toPlainText())}")
check("v1.7.5: the header says WHICH part of the file is on the screen ('the first N of M')",
      i18n.t("sftp.viewer.too_large", limit=format_size(MAX_READ_BYTES)) not in tab.viewer_label.text()
      and i18n.t("sftp.viewer.truncated", shown=format_size(MAX_READ_BYTES),
                 total=format_size(MAX_READ_BYTES + 5)) in tab.viewer_label.text(),
      f"got={tab.viewer_label.text()!r}")
check("v1.7.5: the oversized file WAS read — on the worker thread",
      "/home/big.log" in client4.opened_paths()
      and all(tid != MAIN_THREAD_IDENT for _p, tid in client4.opens))
check("v1.7.5: the read task carried the pane's ceiling (the worker reads no config)",
      tab.viewer_cap() == MAX_READ_BYTES)
tab.close_viewer()

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
      and item_by_name(tab, "big.log").toolTip(0) == "")
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
# 8. v1.9.3: the reader's encoding CHOICE (`ui_viewer_encoding`)
# ════════════════════════════════════════════════════════════
print("== 8. sftp tab: the reader's encoding choice ==")

# The declared list, its normaliser and the key's two readers — PURE, no widget involved.
check("§8 the offered codecs are ONE declared tuple and `auto` is its default",
      STAB.VIEWER_ENCODINGS[0] == STAB.VIEWER_ENCODING_DEFAULT == "auto"
      and {"utf-8", "cp1251", "latin-1"} <= set(STAB.VIEWER_ENCODINGS)
      and len(STAB.VIEWER_ENCODINGS) == len(set(STAB.VIEWER_ENCODINGS)),
      str(STAB.VIEWER_ENCODINGS))
check("§8 a value outside the list (a hand-edited config, a number, a case variant) is normalised",
      STAB.normalize_viewer_encoding("CP1251") == "cp1251"
      and STAB.normalize_viewer_encoding("utf-16") == "auto"
      and STAB.normalize_viewer_encoding(None) == "auto"
      and STAB.normalize_viewer_encoding(7) == "auto")
check("§8 the reader falls back to `auto` for a missing/unusable key",
      STAB.resolve_viewer_encoding({}) == "auto"
      and STAB.resolve_viewer_encoding({STAB.VIEWER_ENCODING_CONFIG: "koi8-r"}) == "koi8-r"
      and STAB.resolve_viewer_encoding({STAB.VIEWER_ENCODING_CONFIG: "no-such-codec"}) == "auto"
      and STAB.resolve_viewer_encoding({STAB.VIEWER_ENCODING_CONFIG: True}) == "auto")
write_cfg({})
check("§8 the writer stores the NORMALISED value and the round trip through config.json is real",
      STAB.save_viewer_encoding("cp866") and read_cfg().get(STAB.VIEWER_ENCODING_CONFIG) == "cp866"
      and STAB.resolve_viewer_encoding() == "cp866"
      and STAB.save_viewer_encoding("nonsense")
      and read_cfg().get(STAB.VIEWER_ENCODING_CONFIG) == "auto")
write_cfg({})

# The decode: `auto` is the shipped rule, a NAMED codec is tried FIRST with it as the fallback.
_CYR = "\u041f\u0440\u0438\u0432\u0435\u0442, \u043c\u0438\u0440\n"       # "Привет, мир"
_CYR_1251 = _CYR.encode("cp1251")
check("§8 the chosen codec decodes what the shipped rule cannot",
      decode_text(_CYR_1251, encoding="cp1251") == (_CYR, "cp1251")
      and decode_text(_CYR_1251)[1] == "latin-1"
      and decode_text(_CYR_1251)[0] != _CYR)
check("§8 a choice the bytes contradict falls back to the shipped rule (never an exception)",
      decode_text(b"caf\xe9", encoding="latin-1") == ("caf\u00e9", "latin-1")
      and decode_text(_CYR_1251, encoding="utf-8")[1] == "latin-1"
      and decode_text(b"\xff\xfe", encoding="utf-8")[1] == "latin-1")
check("§8 a named MULTI-byte codec holds an incomplete tail back too (the cap's rule is shared)",
      decode_text(_CYR.encode("utf-8")[:-2], truncated=True, encoding="utf-8")
      == (_CYR[:-2], "utf-8"),
      repr(decode_text(_CYR.encode("utf-8")[:-2], truncated=True, encoding="utf-8")))
check("§8 `auto` keeps the shipped behaviour BYTE FOR BYTE (a complete Latin-1 file keeps its last char)",
      decode_text(b"caf\xe9", encoding="auto") == ("caf\u00e9", "latin-1")
      and decode_text(b"caf\xe9", truncated=True)[0] == "caf")

# ── the pane and the container, over the live (fake) transport ──
_orig_thread_cls8 = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeSSHThread
win8 = None
try:
    fs8 = FakeSftpFS()
    fs8.add_dir("/etc")
    fs8.add_file("/etc/cyr.txt", _CYR_1251)
    client8 = RecordingSftpClient(fs8)
    win8 = ST.SSHTerminalWindow(
        ServerData(id="viewer-8", alias="viewer8", host="10.99.0.2", user="root"), None,
        password="pw")
    win8.terminal_thread.client = _FakeSshClient(client8)
    win8.tabs.setCurrentIndex(1)
    wait_until(lambda: win8._sftp_worker is not None and win8.sftp_tab.tree.topLevelItemCount() >= 1,
               timeout_ms=5000)
    tab8 = win8.sftp_tab
    tab8._navigate("/etc")
    wait_until(lambda: item_by_name(tab8, "cyr.txt") is not None, timeout_ms=5000)
    tab8._on_item_double_clicked(item_by_name(tab8, "cyr.txt"), 0)
    wait_until(lambda: not tab8.viewer.isHidden(), timeout_ms=5000)
    check("§8 under `auto` a CP1251 file arrives as mojibake (the shipped rule cannot know the codec)",
          tab8.viewer_encoding_choice == "auto" and tab8.viewer_encoding == "latin-1"
          and tab8.viewer_text.toPlainText() != _CYR,
          f"{tab8.viewer_encoding_choice}/{tab8.viewer_encoding}")

    _menu8 = tab8._build_viewer_menu()
    check("§8 the reader's menu carries ONE submenu of the declared codecs",
          sorted(tab8._encoding_actions) == sorted(STAB.VIEWER_ENCODINGS)
          and tab8._encoding_menu.title() == i18n.t("sftp.viewer.encoding")
          and len(tab8._encoding_menu.actions()) == len(STAB.VIEWER_ENCODINGS))
    check("§8 ...with the CURRENT value checked, `auto` as a translated word and a codec as its OWN name",
          tab8._encoding_actions["auto"].isChecked()
          and not tab8._encoding_actions["cp1251"].isChecked()
          and tab8._encoding_actions["auto"].text() == i18n.t("sftp.viewer.encoding_auto")
          and tab8._encoding_actions["cp1251"].text() == "cp1251")
    _menu8.deleteLater()

    check("§8 the CONTAINER owns the value: the choice is persisted under ONE key and walked to the panes",
          tab8._container.apply_viewer_encoding("cp1251") == "cp1251"
          and read_cfg().get(STAB.VIEWER_ENCODING_CONFIG) == "cp1251"
          and tab8.viewer_encoding_choice == "cp1251",
          str(read_cfg().get(STAB.VIEWER_ENCODING_CONFIG)))
    check("§8 ...and the open preview is RE-READ, so the text on the screen IS the chosen decoding",
          wait_until(lambda: tab8.viewer_text.toPlainText() == _CYR, timeout_ms=5000) is not False
          and tab8.viewer_encoding == "cp1251"
          and tab8.viewer_label.text().endswith(
              i18n.t("sftp.viewer.encoding_note", encoding="cp1251")),
          f"{tab8.viewer_encoding} / {tab8.viewer_label.text()!r}")
    _menu8b = tab8._build_viewer_menu()
    check("§8 the submenu of a REBUILD mirrors the pane (a menu never keeps a stale checkmark)",
          tab8._encoding_actions["cp1251"].isChecked()
          and not tab8._encoding_actions["auto"].isChecked())
    _menu8b.deleteLater()

    # A choice the file cannot be read with: the shipped rule still shows it, and the header says so.
    tab8.set_viewer_encoding("utf-8", persist=False, reread=False)
    tab8._show_viewer("/etc/cyr.txt", len(_CYR_1251), "mojibake", "latin-1")
    check("§8 a choice that could NOT read the file is NAMED in the header (never passed off as the result)",
          i18n.t("sftp.viewer.encoding_failed", encoding="utf-8", fallback="latin-1")
          in tab8.viewer_label.text()
          and i18n.t("sftp.viewer.encoding_note", encoding="latin-1")
          not in tab8.viewer_label.text(),
          repr(tab8.viewer_label.text()))
    tab8.set_viewer_encoding("auto", persist=False, reread=False)
    tab8._show_viewer("/etc/cyr.txt", len(_CYR_1251), "mojibake", "latin-1")
    check("§8 ...while under `auto` the shipped note stands unchanged",
          tab8.viewer_label.text().endswith(i18n.t("sftp.viewer.encoding_note", encoding="latin-1")))
    check("§8 a pane with nothing open simply carries the choice into its next read",
          tab8.close_viewer() is None and tab8.set_viewer_encoding("cp1251", persist=False) == "cp1251"
          and len(tab8._read_tasks) == 0)

    win8.page.shutdown()
finally:
    if win8 is not None:
        try:
            win8.close()
            app.processEvents()
        except Exception:  # noqa: BLE001 — the teardown must not mask the checks
            pass
    ST.SSHTerminalThread = _orig_thread_cls8
    write_cfg({})


# ════════════════════════════════════════════════════════════
# 9. i18n + the release state
# ════════════════════════════════════════════════════════════
print("== 9. i18n: sftp.viewer.* keys x4 ==")

VIEWER_KEYS = [
    "sftp.viewer.header", "sftp.viewer.close_tooltip", "sftp.viewer.reading",
    "sftp.viewer.binary", "sftp.viewer.too_large", "sftp.viewer.encoding_note",
    "sftp.viewer.read_failed", "sftp.viewer.encoding", "sftp.viewer.encoding_auto",
    "sftp.viewer.encoding_failed",
]
check("exactly 10 sftp.viewer.* keys are used in the code", len(VIEWER_KEYS) == 10)

for code in ("en", "ru", "zh", "de"):
    i18n.set_language(code)
    missing = [k for k in VIEWER_KEYS if i18n.t(k) == k or not i18n.t(k).strip()]
    check(f"{code}: all the 10 sftp.viewer.* keys are translated (not empty, not the raw ones)",
          not missing, f"missing={missing}")

i18n.set_language("en")  # the default for cleanliness
check_i18n_parity(load_i18n_langs(ROOT))

check_release_state(ROOT)

finish()
