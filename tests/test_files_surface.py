# -*- coding: utf-8 -*-
"""The Files surface (v1.7.3): the cross-session send, the per-server memory, the pane drop, the wrapping reader.

Offscreen, NO network (the fake threads of `_fakes.py`). §1 the per-server directory memory (the pure
map, the restore, the vanished folder); §2 the relay (byte-for-byte, atomic, the oversize refusal, the
cancel, the same-host server-side path, the conflict facts); §3 the row dropped INTO a pane; §4 the
reader's word wrap; §5 the provider of the window and the release state. Contract — `AGENTS.md`
§4.3/§4.24; mechanism — `DOCUMENTATION.md` §66.

Run: python tests/test_files_surface.py   (from the project root) or python tests/run_all.py"""
import os
import sys
import time

from _common import (bootstrap, check, finish, wait_until, clear_cfg, write_cfg, load_i18n_langs,
                     check_i18n_parity, check_i18n_format, check_release_state, read_cfg,
                     releases_at_least, EXPECTED_APP_VERSION)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation)

from PySide6.QtCore import QMimeData, QPoint, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QTreeWidgetItem, QWidget

app = QApplication(sys.argv)

import i18n  # noqa: E402
import modules.sftp_send as SEND  # noqa: E402
import modules.sftp_tab as STAB  # noqa: E402
import modules.ssh_terminal as ST  # noqa: E402
import ui.main_window as MW  # noqa: E402
from models.server import ServerData  # noqa: E402
from modules.command_history import history_key  # noqa: E402
from modules.sftp_tab import (DIRS_CONFIG, MAX_REMEMBERED_DIRS, PANE_DRAG_MIME, SftpTab,
                              VIEWER_WRAP_CONFIG, load_remembered_dirs, pane_payload, remember_dir,
                              remembered_dir_for, resolve_viewer_wrap, save_viewer_wrap)  # noqa: E402
from modules.sftp_worker import (KIND_COPY, KIND_DOWNLOAD, KIND_UPLOAD, PART_SUFFIX,
                                 SftpWorker)  # noqa: E402

from _fakes import EventLog, FakeSSHClient, FakeSSHThread, FakeSftpClient, FakeSftpFS, wire_worker  # noqa: E402


class _FakeMessageBox:
    """`QMessageBox` — the static `question()` AND the conflict dialog's instance API.

    SCRIPT — the scripted answers of the conflict dialogs, one tuple per question:
    ("overwrite" | "skip" | "rename" | None, apply_all); the shipped `ask_conflict()` blocks on a
    real `exec()`, which no offscreen test may do.
    """

    Yes, No = 0x4000, 0x10000
    SCRIPT = []

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
        self.facts = ""

    @staticmethod
    def question(*args, **kwargs):
        return _FakeMessageBox.Yes

    def setWindowTitle(self, text):
        pass

    def setIcon(self, icon):
        pass

    def setText(self, text):
        pass

    def setInformativeText(self, text):
        self.facts = text

    def addButton(self, text, role=None):
        button = _Button(text)
        self._buttons[text] = button
        return button

    def setCheckBox(self, box):
        self._checkbox = box

    def exec(self):
        action, apply_all = (self.SCRIPT.pop(0) if self.SCRIPT else ("overwrite", False))
        labels = {"overwrite": i18n.t("sftp.conflict.overwrite"),
                  "skip": i18n.t("sftp.conflict.skip"),
                  "rename": i18n.t("sftp.conflict.rename")}
        self._clicked = self._buttons.get(labels.get(action)) if action else None
        if self._checkbox is not None:
            self._checkbox.setChecked(bool(apply_all) and action is not None)

    def clickedButton(self):
        return self._clicked


class _Button:
    """The button handle `ask_conflict()` compares against `clickedButton()`."""

    def __init__(self, text):
        self._text = text

    def text(self):
        return self._text


STAB.QMessageBox = _FakeMessageBox


def one_worker(fs, chunk_delay=0.0, deny_dirs=frozenset()):
    """(worker, log, client) over one in-memory remote FS — no widget, no network."""
    fs.deny_dirs = set(deny_dirs)
    client = FakeSftpClient(fs, chunk_delay=chunk_delay)
    client.copy_data_ok = False
    worker = SftpWorker(client)
    log = EventLog()
    wire_worker(worker, log)
    worker.start()
    return worker, log, client


def make_tab(fs, commander=False, key="", host="10.10.0.1", port=22):
    """(tab, worker, log, messages) — the listing of "/" rendered, an IDENTITY installed."""
    worker, log, _client = one_worker(fs)
    tab = SftpTab()
    msgs = []
    tab.message.connect(msgs.append)
    tab.set_session_info(key=key or "key-src", label="alpha", host=host, port=port)
    if commander:
        tab.set_commander(True)
    tab.set_worker(worker)
    wait_until(lambda: tab.tree.topLevelItemCount() >= 1, timeout_ms=5000)
    return tab, worker, log, msgs


def item_by_name(pane, name):
    for index in range(pane.tree.topLevelItemCount()):
        item = pane.tree.topLevelItem(index)
        if item.text(0) == name:
            return item
    return None


def started_kinds(log):
    return [e[2] for e in log.events if e[0] == "started"]


def spool_files():
    """The live spools under the OS temp (the relay's ONE local trace)."""
    try:
        names = os.listdir(SEND.spool_dir())
    except OSError:
        return []
    return sorted(n for n in names if n.startswith(SEND.SPOOL_PREFIX))


def age_file(path, seconds):
    """Push a file's mtime `seconds` into the past (the sweep's rule is an AGE, not a name)."""
    old = time.time() - float(seconds)
    try:
        os.utime(path, (old, old))
    except OSError:
        pass


def drop_event(mime, pos=QPoint(500, 500), action=Qt.DropAction.CopyAction,
               modifiers=Qt.KeyboardModifier.NoModifier):
    return QDropEvent(pos, action, mime, Qt.MouseButton.LeftButton, modifiers)


def row_item(tab, path, is_dir=False, size=0, mtime=0):
    """A listing row built by hand (the submenu's seam — no transport needed)."""
    item = QTreeWidgetItem(tab.tree)
    item.setText(0, os.path.basename(path))
    item.setData(0, tab.PATH_ROLE, path)
    item.setData(0, tab.ISDIR_ROLE, is_dir)
    item.setData(0, tab.SIZE_ROLE, size)
    item.setData(0, tab.MTIME_ROLE, mtime)
    return item


# ════════════════════════════════════════════════════════════
# 1. The per-server directory memory
# ════════════════════════════════════════════════════════════
print("== 1. the panes remember WHERE a server was left ==")

clear_cfg()
check("the map is PURE and moves ONE entry to the END (insertion order IS the age)",
      list(remember_dir({"a": "/1", "b": "/2"}, "a", "/3")) == ["b", "a"]
      and remember_dir({"a": "/1"}, "a", "/3") == {"a": "/3"})
check("a blank key or a RELATIVE path changes nothing (a remote directory is absolute)",
      remember_dir({"a": "/1"}, "", "/2") == {"a": "/1"}
      and remember_dir({"a": "/1"}, "b", "relative") == {"a": "/1"})
_capped = remember_dir({f"k{n}": f"/d{n}" for n in range(MAX_REMEMBERED_DIRS)}, "new", "/new")
check(f"the map is BOUNDED and evicts the OLDEST over the cap ({MAX_REMEMBERED_DIRS})",
      len(_capped) == MAX_REMEMBERED_DIRS and "k0" not in _capped and _capped.get("new") == "/new",
      f"len={len(_capped)}")
check("the reader answers the entry of ONE key and '' for anything unknown",
      remembered_dir_for({"a": "/1"}, "a") == "/1" and remembered_dir_for({"a": "/1"}, "zz") == ""
      and remembered_dir_for("broken", "a") == "")

write_cfg({DIRS_CONFIG: {"k1": "/var/log", "bad": "relative", "no": 7}})
check("a FOREIGN entry of the stored map is dropped (a broken config navigates nobody)",
      load_remembered_dirs() == {"k1": "/var/log"}, str(load_remembered_dirs()))
write_cfg({DIRS_CONFIG: "true"})
check("a foreign VALUE answers an empty map (never `dict('true')`)", load_remembered_dirs() == {})
clear_cfg()

fs1 = FakeSftpFS()
fs1.add_dir("/var")
fs1.add_dir("/var/log")
tab1, worker1, _log1, _msgs1 = make_tab(fs1, key="remember-me", host="10.10.0.9")
tab1.active_pane._relist("/var/log")
wait_until(lambda: tab1.active_pane.path_label.text() == "/var/log", timeout_ms=5000)
check("a directory the SERVER answered for is remembered (the listing, never the keystroke)",
      tab1.remembered_dir() == "/var/log" and tab1.session_key() == "remember-me")
check("...and only the entries THIS container moved are its own write payload",
      tab1._dirs_touched == {"remember-me": "/var/log"}, str(tab1._dirs_touched))
payload1 = tab1.merge_dirs_into({"ui_terminal_split": True})
check("the memory rides out under ONE key, next to the window's own (merge-on-write)",
      payload1.get("ui_terminal_split") is True
      and payload1.get(DIRS_CONFIG) == {"remember-me": "/var/log"}, str(payload1))
check("the commander's own payload is NOT the home of the memory (its contract stays two keys)",
      set(tab1.commander_extra_config()) == {"ui_sftp_commander", "ui_sftp_commander_ratio"})
tab1.set_worker(None)
worker1.shutdown(wait_ms=2000)

clear_cfg()
write_cfg({DIRS_CONFIG: {"remember-me": "/var/log"}})
tab2, worker2, _log2, _msgs2 = make_tab(fs1, key="remember-me", host="10.10.0.9")
wait_until(lambda: tab2.active_pane.path_label.text() == "/var/log", timeout_ms=5000)
check("a pane is BUILT in the directory its server was left in (restored on the first transport)",
      tab2.active_pane.current_dir == "/var/log"
      and tab2.active_pane.path_label.text() == "/var/log")
tab2.set_worker(None)
worker2.shutdown(wait_ms=2000)

clear_cfg()
write_cfg({DIRS_CONFIG: {"gone-key": "/no/such/dir"}})
fs2 = FakeSftpFS()
fs2.add_file("/root.txt", b"root")
tab3, worker3, _log3, msgs3 = make_tab(fs2, key="gone-key", host="10.10.0.8")
wait_until(lambda: bool(msgs3), timeout_ms=5000)
check("a remembered directory that is GONE falls back to the shipped opening rule",
      tab3.active_pane.current_dir == "/", tab3.active_pane.current_dir)
check("...and says so in ONE status line (a restored path is a hint, not a command)",
      i18n.t("sftp.dir_missing", path="/no/such/dir", fallback="/") in msgs3, str(msgs3))
tab3.set_worker(None)
worker3.shutdown(wait_ms=2000)
clear_cfg()


# ════════════════════════════════════════════════════════════
# 2. The cross-session relay
# ════════════════════════════════════════════════════════════
print("== 2. Send to…: the two legs, the spool and the two declared paths ==")

DATA = b"payload-" * 4096   # 32 KB — one whole chunk
check("the ceiling of ONE send is the declared constant (100 MB)",
      SEND.MAX_SEND_BYTES == 100 * 1024 * 1024 and SEND.size_allowed(SEND.MAX_SEND_BYTES)
      and not SEND.size_allowed(SEND.MAX_SEND_BYTES + 1))
check("only a real (host, ssh_port, user) triple is 'the same host' (an unknown host or user is a relay)",
      SEND.same_host(SEND.SendEndpoint(host="h", port=22, user="root"),
                     SEND.SendEndpoint(host="H", port=22, user="root"))
      and not SEND.same_host(SEND.SendEndpoint(host="h", user="root"),
                             SEND.SendEndpoint(host="h", port=2222, user="root"))
      and not SEND.same_host(SEND.SendEndpoint(host="h", port=22, user="root"),
                             SEND.SendEndpoint(host="h", port=22, user="alice"))
      and not SEND.same_host(SEND.SendEndpoint(host="h", port=22),
                             SEND.SendEndpoint(host="h", port=22))
      and not SEND.same_host(SEND.SendEndpoint(), SEND.SendEndpoint()))

SEND.sweep_spools()
fs_src = FakeSftpFS()
fs_src.add_dir("/in")
fs_src.add_file("/in/app.bin", DATA)
fs_dst = FakeSftpFS()
fs_dst.add_dir("/out")
src_worker, src_log, _c = one_worker(fs_src)
dst_worker, dst_log, _c2 = one_worker(fs_dst)
source = SEND.SendEndpoint(key="k-src", label="alpha", host="10.10.0.1", port=22,
                           worker=src_worker, directory="/in")
target = SEND.SendEndpoint(key="k-dst", label="beta", host="10.10.0.2", port=22,
                           worker=dst_worker, directory="/out")
entry = {"path": "/in/app.bin", "name": "app.bin", "size": len(DATA), "mtime": 1700000000}
relay = SEND.SendRelay(source, target, entry)
results = []
relay.finished.connect(results.append)
relay.start("/out")
check("another host takes the RELAY path (source → spool → target, no server-to-server copy)",
      relay.strategy == SEND.SEND_STRATEGY_RELAY)
check("the spool is ONE file under the OS temp, prepared with its provisional twin",
      relay.spool.startswith(SEND.spool_dir())
      and os.path.basename(relay.spool).startswith(SEND.SPOOL_PREFIX)
      and os.path.exists(relay.spool + PART_SUFFIX), relay.spool)
wait_until(lambda: results, timeout_ms=15000)
check("the file lands in the target session's folder BYTE FOR BYTE",
      fs_dst.files.get("/out/app.bin") == DATA,
      f"got={len(fs_dst.files.get('/out/app.bin') or b'')} bytes")
check("...and the store is ATOMIC (no provisional file is left on the target)",
      not [p for p in fs_dst.files if p.endswith(PART_SUFFIX)], str(list(fs_dst.files)))
check("the spool is deleted on SUCCESS (a plaintext copy never outlives the send)",
      not os.path.exists(relay.spool) and not os.path.exists(relay.spool + PART_SUFFIX)
      and spool_files() == [], str(spool_files()))
check("the two legs are the SHIPPED worker kinds (download on the source, upload on the target)",
      started_kinds(src_log) == [KIND_DOWNLOAD] and started_kinds(dst_log) == [KIND_UPLOAD],
      f"{started_kinds(src_log)} / {started_kinds(dst_log)}")
check("ONE result names the path taken, the folder and the size",
      bool(results) and results[0]["ok"] and results[0]["strategy"] == SEND.SEND_STRATEGY_RELAY
      and results[0]["dir"] == "/out" and results[0]["bytes"] == len(DATA), str(results[:1]))

# the same host: ONE server-side copy on the SOURCE worker, no spool and no second hop
SEND.sweep_spools()
fs_same = FakeSftpFS()
fs_same.add_dir("/a")
fs_same.add_dir("/b")
fs_same.add_file("/a/same.bin", DATA)
same_worker, same_log, _c3 = one_worker(fs_same)
same_src = SEND.SendEndpoint(key="s1", host="10.10.0.7", port=22, user="root",
                             worker=same_worker, directory="/a")
same_dst = SEND.SendEndpoint(key="s2", host="10.10.0.7", port=22, user="root",
                             worker=same_worker, directory="/b")
relay_same = SEND.SendRelay(same_src, same_dst, dict(entry, path="/a/same.bin", name="same.bin"))
same_results = []
relay_same.finished.connect(same_results.append)
relay_same.start("/b")
check("the SAME host takes the server-side path (`queue_copy`, no spool at all)",
      relay_same.strategy == SEND.SEND_STRATEGY_SERVER and relay_same.spool == "")
wait_until(lambda: same_results, timeout_ms=15000)
check("...and the copy really landed (ONE kind, ONE worker, the file byte for byte)",
      fs_same.files.get("/b/same.bin") == DATA
      and started_kinds(same_log) == [KIND_COPY], str(started_kinds(same_log)))
check("a server-side send creates NO spool file", spool_files() == [], str(spool_files()))
check("the result says which of the two declared paths ran",
      same_results[0]["strategy"] == SEND.SEND_STRATEGY_SERVER and same_results[0]["ok"])

# a failing store: the destination is untouched and the spool is still dropped
SEND.sweep_spools()
fs_bad = FakeSftpFS()
fs_bad.add_dir("/in")
fs_bad.add_dir("/out")
fs_bad.add_file("/in/bad.bin", DATA)
bad_src_worker, _bl, _c4 = one_worker(fs_bad)
bad_dst_worker, _bl2, _c5 = one_worker(fs_bad, deny_dirs={"/out"})
bad_relay = SEND.SendRelay(
    SEND.SendEndpoint(key="b1", host="h1", worker=bad_src_worker, directory="/in"),
    SEND.SendEndpoint(key="b2", host="h2", worker=bad_dst_worker, directory="/out"),
    {"path": "/in/bad.bin", "name": "bad.bin", "size": len(DATA), "mtime": 0})
bad_results = []
bad_relay.finished.connect(bad_results.append)
bad_relay.start("/out")
wait_until(lambda: bad_results, timeout_ms=15000)
check("a refused store leaves the target EXACTLY as it was (no half file, no provisional name)",
      "/out/bad.bin" not in fs_bad.files
      and not [p for p in fs_bad.files if p.endswith(PART_SUFFIX)], str(list(fs_bad.files)))
check("...and the failure is reported with the spool already gone",
      bool(bad_results) and bad_results[0]["ok"] is False and bad_results[0]["error"]
      and spool_files() == [], str(bad_results[:1]))

# a cancel: the spool goes with it
SEND.sweep_spools()
fs_cancel = FakeSftpFS()
fs_cancel.add_dir("/in")
fs_cancel.add_dir("/out")
fs_cancel.add_file("/in/big.bin", b"x" * (32 * 1024 * 16))
cancel_src_worker, cancel_log, _c6 = one_worker(fs_cancel, chunk_delay=0.05)
cancel_dst_worker, _cl, _c7 = one_worker(fs_cancel)
cancel_relay = SEND.SendRelay(
    SEND.SendEndpoint(key="c1", host="h1", worker=cancel_src_worker, directory="/in"),
    SEND.SendEndpoint(key="c2", host="h2", worker=cancel_dst_worker, directory="/out"),
    {"path": "/in/big.bin", "name": "big.bin", "size": 32 * 1024 * 16, "mtime": 0})
cancel_results = []
cancel_relay.finished.connect(cancel_results.append)
cancel_relay.start("/out")
wait_until(lambda: KIND_DOWNLOAD in started_kinds(cancel_log), timeout_ms=5000)
cancel_relay.cancel()
wait_until(lambda: cancel_results, timeout_ms=15000)
check("a Cancel ends the send without a target file",
      bool(cancel_results) and cancel_results[0]["ok"] is False
      and "/out/big.bin" not in fs_cancel.files, str(cancel_results[:1]))
check("...and DELETES the spool (the acceptance sentence of the release)",
      spool_files() == [], str(spool_files()))

_stale_a = SEND.spool_path("stale-a", token=1)
_stale_b = SEND.spool_path("stale-b", token=2)
_live = SEND.create_spool("live-sibling")
_prepared = (SEND.prepare_spool(_stale_a) and SEND.prepare_spool(_stale_b)
             and bool(_live) and SEND.prepare_spool(_live))
age_file(_stale_a + PART_SUFFIX, SEND.SPOOL_MAX_AGE_SEC + 60)
age_file(_stale_b + PART_SUFFIX, SEND.SPOOL_MAX_AGE_SEC + 60)
_removed = SEND.sweep_spools()
check("the sweep takes the CRASHED run's spools by AGE and leaves a LIVE instance's own alone",
      _prepared and _removed >= 2
      and not os.path.exists(_stale_a + PART_SUFFIX) and not os.path.exists(_stale_b + PART_SUFFIX)
      and os.path.exists(_live) and os.path.exists(_live + PART_SUFFIX),
      f"prepared={_prepared} removed={_removed} left={spool_files()}")
SEND.drop_spool(_live)
_young_path = SEND.spool_path("young", token=3)
check("a YOUNG spool survives the startup sweep (a live sibling is never cut in half)",
      SEND.prepare_spool(_young_path) and SEND.sweep_spools() == 0
      and os.path.exists(_young_path + PART_SUFFIX), str(spool_files()))
SEND.drop_spool(_young_path)

# the coordinator: the folder question, the conflict facts, the cancelled dialog
class _FakeSendDialog:
    """The `SendFileDialog` seam — the script of chosen folders (`[]` = a cancelled dialog)."""

    SCRIPT = []
    SEEN = []

    def __init__(self, parent=None, entry=None, target=None, folders=(), default_dir="/",
                 same_host=True, user=""):
        self.entry = dict(entry or {})
        self.target = target
        self.folders = list(folders)
        self.default_dir = default_dir
        self.same = same_host
        self.user = user
        self._choice = self.SCRIPT.pop(0) if self.SCRIPT else None
        _FakeSendDialog.SEEN.append(self)

    def exec(self):
        return int(SEND.DIALOG_ACCEPTED) if self._choice else 0

    def chosen_dir(self):
        return self._choice or ""


SEND.SendFileDialog = _FakeSendDialog
SEND.sweep_spools()
fs_c1 = FakeSftpFS()
fs_c1.add_dir("/in")
fs_c1.add_dir("/out")
fs_c1.add_file("/in/one.txt", b"one")
fs_c2 = FakeSftpFS()
fs_c2.add_dir("/in")          # the source's folder EXISTS on the target (the documented default)
fs_c2.add_dir("/out")
c1_worker, c1_log, _c8 = one_worker(fs_c1)
c2_worker, c2_log, _c9 = one_worker(fs_c2)
co_source = SEND.SendEndpoint(key="cs", label="alpha", host="ha", user="root",
                              worker=c1_worker, directory="/in")
co_target = SEND.SendEndpoint(key="ct", label="beta", host="hb", worker=c2_worker, directory="/out",
                              folders=["/out"], facts={"old.txt": (False, 10, 1700000000)})
asked = []
coord = SEND.SendCoordinator(co_source, co_target, {"path": "/in/one.txt", "name": "one.txt",
                                                    "size": 3, "mtime": 1700000000},
                             asker=lambda *a: (asked.append(a) or True))
coord_results = []
coord.finished.connect(coord_results.append)
_FakeSendDialog.SCRIPT = ["/in"]
coord.start()
wait_until(lambda: coord_results, timeout_ms=15000)
check("the dialog is opened with the TARGET's folders and the source folder as the default",
      bool(_FakeSendDialog.SEEN) and _FakeSendDialog.SEEN[-1].folders == ["/out"]
      and _FakeSendDialog.SEEN[-1].default_dir == "/in"
      and _FakeSendDialog.SEEN[-1].same is False,
      str(_FakeSendDialog.SEEN[-1].default_dir if _FakeSendDialog.SEEN else None))
check("the dialog is TOLD the identity the server-side path would run as (the source's user)",
      bool(_FakeSendDialog.SEEN) and _FakeSendDialog.SEEN[-1].user == co_source.user,
      str(_FakeSendDialog.SEEN[-1].user if _FakeSendDialog.SEEN else None))
check("the chosen folder takes the RELAY and the file is there",
      bool(coord_results) and coord_results[0]["ok"] and fs_c2.files.get("/in/one.txt") == b"one")
check("no conflict is asked on a name the target does not have", asked == [], str(asked))

# the conflict: BOTH sides' size and date reach the question, and a refusal sends NOTHING
fs_c2.files["/in/one.txt"] = b"a-much-longer-existing-file"
asked.clear()
target2 = SEND.SendEndpoint(key="ct", label="beta", host="hb", worker=c2_worker, directory="/in",
                            folders=["/in"], facts={"one.txt": (False, 28, 1600000000)})
coord2 = SEND.SendCoordinator(co_source, target2, {"path": "/in/one.txt", "name": "one.txt",
                                                   "size": 3, "mtime": 1700000000},
                              asker=lambda *a: (asked.append(a) or False))
coord2_results = []
coord2.finished.connect(coord2_results.append)
coord2.run("/in")
wait_until(lambda: coord2_results, timeout_ms=10000)
_facts = asked[0][3] if asked else ""
check("the overwrite question carries BOTH sides' size and date (the shipped dialog, one line)",
      bool(asked) and "3 B" in _facts and "28 B" in _facts and len(_facts.split("\n")) == 2,
      repr(_facts))
check("a refused overwrite sends NOTHING (a skipped send is an answer, not a transfer)",
      bool(coord2_results) and coord2_results[0].get("skipped") is True
      and fs_c2.files.get("/in/one.txt") == b"a-much-longer-existing-file")
check("the shipped `ask_conflict()` gained the OPTIONAL facts line (defaulted, so old callers hold)",
      STAB.ask_conflict.__defaults__[-1] == "" and "facts" in STAB.ask_conflict.__code__.co_varnames)

# a cancelled dialog: nothing is transferred and no spool is left behind
SEND.sweep_spools()
_before = len(c1_log.events)
_FakeSendDialog.SCRIPT = []
coord3 = SEND.SendCoordinator(co_source, target2, {"path": "/in/one.txt", "name": "one.txt",
                                                   "size": 3, "mtime": 0}, asker=lambda *a: True)
coord3_results = []
coord3.finished.connect(coord3_results.append)
coord3.start()
wait_until(lambda: coord3_results, timeout_ms=10000)
check("a cancelled dialog is a quiet 'nothing happened' (no transfer, no spool, no task)",
      bool(coord3_results) and coord3_results[0].get("cancelled") is True
      and spool_files() == [] and len(c1_log.events) == _before,
      f"{coord3_results[:1]} spools={spool_files()}")

# an oversize file: refused BEFORE leg 1
_before_big = (len(c1_log.events), len(c2_log.events))
coord_big = SEND.SendCoordinator(co_source, target2,
                                 {"path": "/in/one.txt", "name": "one.txt",
                                  "size": SEND.MAX_SEND_BYTES + 1, "mtime": 0},
                                 asker=lambda *a: True)
big_results = []
big_msgs = []
coord_big.report.connect(big_msgs.append)
coord_big.finished.connect(big_results.append)
coord_big.run("/in")
wait_until(lambda: big_results, timeout_ms=5000)
check("an oversize file is refused BEFORE leg 1 (ONE sentence, no task, no spool)",
      bool(big_results) and big_results[0].get("too_big") is True and bool(big_msgs)
      and (len(c1_log.events), len(c2_log.events)) == _before_big and spool_files() == [],
      f"{big_results[:1]} msgs={big_msgs!r}")

for _w in (src_worker, dst_worker, same_worker, bad_src_worker, bad_dst_worker, cancel_src_worker,
           cancel_dst_worker, c1_worker, c2_worker):
    _w.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 3. The row dropped INTO a pane
# ════════════════════════════════════════════════════════════
print("== 3. a row dragged from one pane into the other ==")

clear_cfg()
fs3 = FakeSftpFS()
fs3.add_dir("/left")
fs3.add_dir("/right")
fs3.add_dir("/left/sub")
fs3.add_file("/left/drop.txt", b"drop-me")
tab4, worker4, _log4, msgs4 = make_tab(fs3, commander=True, key="pane-key", host="10.10.0.5")
pane_l, pane_r = tab4.panes[0], tab4.panes[1]
pane_l._relist("/left")
wait_until(lambda: item_by_name(pane_l, "drop.txt") is not None, timeout_ms=5000)
pane_r._relist("/right")
wait_until(lambda: pane_r.path_label.text() == "/right", timeout_ms=5000)

mime4 = pane_l.tree.drag_mime(item_by_name(pane_l, "drop.txt"))
payload4 = pane_payload(mime4)
check("the drag payload of a row is the path PLUS the pane's identity (the private type)",
      mime4.text() == "/left/drop.txt" and mime4.hasFormat(PANE_DRAG_MIME)
      and payload4["session"] == "pane-key" and payload4["pane"] == id(pane_l)
      and payload4["path"] == "/left/drop.txt", str(payload4))
check("a foreign drag (an empty payload, nothing at all) is not a pane payload",
      pane_payload(QMimeData()) is None and pane_payload(None) is None)
_broken = QMimeData()
_broken.setData(PANE_DRAG_MIME, b"{not json")
check("a malformed payload is a FOREIGN drag, never an exception", pane_payload(_broken) is None)

ev_enter = QDragEnterEvent(QPoint(500, 500), Qt.DropAction.CopyAction, mime4,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
pane_r.dragEnterEvent(ev_enter)
check("the pane ACCEPTS a row of another pane (the private type is a drop payload)",
      ev_enter.isAccepted())
pane_l.dropEvent(drop_event(mime4))
check("a drop on the pane the row CAME FROM is refused with ONE sentence",
      i18n.t("sftp.cmd.drop_same_pane") in msgs4, str(msgs4))

msgs4.clear()
_far = pane_l.tree.drag_mime(item_by_name(pane_l, "drop.txt"))
_far.setData(PANE_DRAG_MIME, b'{"session": "another-session", "pane": 1, "path": "/x"}')
pane_r.dropEvent(drop_event(_far))
check("a row of ANOTHER session is refused (no server-to-server path exists)",
      i18n.t("sftp.cmd.drop_other_session") in msgs4
      and not [p for p in fs3.files if p.startswith("/right/")], str(msgs4))

msgs4.clear()
# The destination already holds the name, so the SHIPPED conflict question is asked; "overwrite"
# is the scripted answer (the copy dialog never runs `exec()` offscreen).
_FakeMessageBox.SCRIPT = [("overwrite", False)]
pane_r.dropEvent(drop_event(mime4))
wait_until(lambda: fs3.files.get("/right/drop.txt") == b"drop-me", timeout_ms=8000)
check("a drop is a COPY into the pane under the cursor (the shipped batch)",
      fs3.files.get("/right/drop.txt") == b"drop-me"
      and fs3.files.get("/left/drop.txt") == b"drop-me")
report_copy = i18n.t("sftp.cmd.copy_report", done=1, skipped=0, failed=0)
wait_until(lambda: report_copy in msgs4, timeout_ms=5000)
check("...with the SHIPPED closing report (one sentence per batch)", report_copy in msgs4,
      str(msgs4))

msgs4.clear()
_FakeMessageBox.SCRIPT = [("overwrite", False)]
pane_r.dropEvent(drop_event(mime4, action=Qt.DropAction.MoveAction,
                            modifiers=Qt.KeyboardModifier.ShiftModifier))
wait_until(lambda: "/left/drop.txt" not in fs3.files, timeout_ms=8000)
check("`Shift`+drop is a MOVE (the classic commander reading of the gesture)",
      "/left/drop.txt" not in fs3.files and fs3.files.get("/right/drop.txt") == b"drop-me")
report_move = i18n.t("sftp.cmd.move_report", done=1, skipped=0, failed=0)
wait_until(lambda: report_move in msgs4, timeout_ms=5000)
check("...reported by the MOVE vocabulary", report_move in msgs4, str(msgs4))
check("the drop helper is a PURE reading of the gesture (the action and the modifier)",
      pane_r._drop_is_move(drop_event(mime4, action=Qt.DropAction.MoveAction)) is True
      and pane_r._drop_is_move(drop_event(mime4)) is False)
tab4.set_worker(None)
worker4.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 4. The reader that wraps
# ════════════════════════════════════════════════════════════
print("== 4. Word wrap in the reader's own menu ==")

clear_cfg()
check("the setting is a PURE reader with the shipped default (no config = no wrap)",
      resolve_viewer_wrap({}) is False and resolve_viewer_wrap({VIEWER_WRAP_CONFIG: True}) is True
      and resolve_viewer_wrap({VIEWER_WRAP_CONFIG: "true"}) is False
      and resolve_viewer_wrap({VIEWER_WRAP_CONFIG: 1}) is False)
check("the writer stores a REAL bool (and the reader gets it back)",
      save_viewer_wrap(True) and read_cfg().get(VIEWER_WRAP_CONFIG) is True
      and resolve_viewer_wrap() is True)
write_cfg({VIEWER_WRAP_CONFIG: True})
fs4 = FakeSftpFS()
fs4.add_file("/long.txt", b"x = 1\n" + b"y" * 400 + b"\n")
fs4.add_file("/data.json", b'{\n  "a": 1,\n  "b": [2, 3]\n}\n')
tab5, worker5, _log5, _msgs5 = make_tab(fs4, commander=True, key="wrap-key", host="10.10.0.6")
pane5_l, pane5_r = tab5.panes[0], tab5.panes[1]
check("a pane is BUILT with the stored mode (both panes and every session agree)",
      pane5_l.viewer_wrap is True
      and pane5_l.viewer_text.lineWrapMode() == STAB.QPlainTextEdit.LineWrapMode.WidgetWidth
      and pane5_r.viewer_wrap is True)
check("the lazy window is WIDENED under wrapping (one block is several visual rows there)",
      pane5_l._lazy_margin() == pane5_l.VIEWER_LAZY_MARGIN * pane5_l.WRAP_MARGIN_FACTOR
      and pane5_l.VIEWER_LAZY_MARGIN == STAB.syntax.VIEWER_LAZY_MARGIN)

tab5.resize(900, 600)
tab5.show()
app.processEvents()
pane5_l._relist("/")
wait_until(lambda: item_by_name(pane5_l, "data.json") is not None, timeout_ms=5000)
pane5_l._open_viewer(item_by_name(pane5_l, "data.json"))
wait_until(lambda: pane5_l._viewer_open, timeout_ms=5000)
for _ in range(4):
    app.processEvents()
_highlighted = pane5_l._highlight_visible(force=True)
_wrapped_range = pane5_l._viewer_block_range()
check("the preview still detects the language and colours the visible window UNDER wrap",
      pane5_l.viewer_language == "json" and pane5_l.viewer_highlighter is not None
      and _wrapped_range is not None and _highlighted > 0,
      f"lang={pane5_l.viewer_language} hl={_highlighted}")

menu5 = pane5_l._build_viewer_menu()
_titles = [a.text() for a in menu5.actions()]
check("the reader's menu is Qt's OWN standard one PLUS the app's row",
      len(_titles) >= 3 and i18n.t("sftp.viewer.word_wrap") in _titles, str(_titles))
_wrap_act = [a for a in menu5.actions() if a.text() == i18n.t("sftp.viewer.word_wrap")]
check("the row is ONE checkable QAction, checked from the live state",
      len(_wrap_act) == 1 and _wrap_act[0].isCheckable() and _wrap_act[0].isChecked() is True)
_wrap_act[0].setChecked(False)     # the real toggled(bool) path (Qt gotcha #10)
for _ in range(4):
    app.processEvents()
check("toggling the row turns the wrap OFF on EVERY pane and writes the ONE key",
      pane5_l.viewer_wrap is False and pane5_r.viewer_wrap is False
      and pane5_l.viewer_text.lineWrapMode() == STAB.QPlainTextEdit.LineWrapMode.NoWrap
      and read_cfg().get(VIEWER_WRAP_CONFIG) is False, str(read_cfg().get(VIEWER_WRAP_CONFIG)))
_unwrapped_range = pane5_l._viewer_block_range()
check("the window is honest in BOTH modes (the layout decides the range, not a guess)",
      _unwrapped_range is not None
      and (_wrapped_range[1] - _wrapped_range[0]) <= (_unwrapped_range[1] - _unwrapped_range[0]),
      f"wrapped={_wrapped_range} plain={_unwrapped_range}")
pane5_l._open_viewer(item_by_name(pane5_l, "long.txt"))
wait_until(lambda: pane5_l.viewer_text.toPlainText().startswith("x = 1"), timeout_ms=5000)
_wrap_act2 = [a for a in pane5_l._build_viewer_menu().actions()
              if a.text() == i18n.t("sftp.viewer.word_wrap")][0]
_wrap_act2.setChecked(True)
for _ in range(3):
    app.processEvents()
check("the mode survives a restart (the ONE global key is what a new pane reads)",
      read_cfg().get(VIEWER_WRAP_CONFIG) is True and resolve_viewer_wrap(read_cfg()) is True
      and pane5_l.viewer_wrap is True)
check("a LONG line is really wrapped by the widget (WidgetWidth, not NoWrap)",
      pane5_l.viewer_text.lineWrapMode() == STAB.QPlainTextEdit.LineWrapMode.WidgetWidth
      and pane5_l.viewer_text.toPlainText().count("\n") == 2)
tab5.set_worker(None)
worker5.shutdown(wait_ms=2000)
clear_cfg()


# ════════════════════════════════════════════════════════════
# 5. The provider of the window and the release state
# ════════════════════════════════════════════════════════════
print("== 5. the Send-to provider of the window ==")


class _StubHost(QWidget):
    """The parent-chain hook a container resolves (`find_host_hook`) — a window-like stub."""

    def __init__(self, targets):
        super().__init__()
        self.targets = list(targets)
        self.asked = []

    def _send_session_targets(self, exclude_key=""):
        self.asked.append(exclude_key)
        return [t for t in self.targets if t.key != exclude_key]


fs5 = FakeSftpFS()
fs5.add_file("/p.txt", b"p")
holder = _StubHost([SEND.SendEndpoint(key="other", label="beta", host="hb",
                                      worker=object(), directory="/out")])
tab6 = SftpTab(holder)
tab6.set_session_info(key="mine", label="alpha", host="ha", port=22)
check("the container finds the provider through the PARENT CHAIN (never by importing the window)",
      [t.key for t in tab6.send_targets()] == ["other"] and holder.asked == ["mine"],
      str(holder.asked))
holder.targets = [SEND.SendEndpoint(key="dead", label="beta", host="hb", worker=None)]
check("a target without a live worker is never offered (it cannot receive a file)",
      tab6.send_targets() == [])
check("a detached container offers NOTHING (the menu then says so, once)",
      SftpTab().send_targets() == [])

holder.targets = [SEND.SendEndpoint(key="other", label="beta", host="hb", worker=object(),
                                    directory="/out")]
_item6 = row_item(tab6, "/p.txt", is_dir=False, size=12, mtime=0)
_sub6 = tab6._build_send_menu(_item6)
check("the row's submenu names the live session and its folder",
      [a.text() for a in _sub6.actions()] == ["beta (/out)"], str([a.text() for a in _sub6.actions()]))
check("...and the row itself routes into the container's ONE send door",
      callable(tab6.start_send) and tab6.send_targets()[0].refresh is None)
_dir_item = row_item(tab6, "/out", is_dir=True)
_sub_dir = tab6._build_send_menu(_dir_item)
check("a FOLDER row answers ONE disabled sentence (a directory crosses through the panes)",
      [a.text() for a in _sub_dir.actions()] == [i18n.t("sftp.send.no_file")]
      and not _sub_dir.actions()[0].isEnabled())
tab6.set_worker(None)

# the container's OWN door: `start_send()` drives the whole relay through the pane's question
clear_cfg()
fs_send = FakeSftpFS()
fs_send.add_dir("/in")
fs_send.add_file("/in/box.bin", b"box")
send_worker, _sl, _sc = one_worker(fs_send)
tab7, worker7, _log7, msgs7 = make_tab(fs_send, key="sender-key", host="10.10.0.1")
tab7.set_worker(None)
tab7.set_worker(send_worker)
wait_until(lambda: item_by_name(tab7.active_pane, "in") is not None, timeout_ms=5000)
fs_recv = FakeSftpFS()
fs_recv.add_dir("/in")
fs_recv.add_file("/in/box.bin", b"a-longer-existing-copy")
recv_worker, _rl, _rc = one_worker(fs_recv)
recv_target = SEND.SendEndpoint(key="receiver-key", label="beta", host="10.10.0.2", port=22,
                                worker=recv_worker, directory="/in",
                                folders=["/in"], facts={"box.bin": (False, 23, 1600000000)})
asked7 = []


def _ask7(name, target_dir, remaining, facts=""):
    asked7.append((name, target_dir, facts))
    return ("overwrite", False)


tab7.active_pane._ask_conflict = _ask7
_FakeSendDialog.SCRIPT = ["/in"]
_sent = tab7.start_send(tab7.active_pane, recv_target,
                        {"path": "/in/box.bin", "name": "box.bin", "size": 3, "mtime": 1700000000})
check("the container's ONE send door takes the request (and remembers it as running)",
      _sent is True and "receiver-key" in tab7._sends, str(list(tab7._sends)))
check("...and a SECOND send to the same target is refused while the first runs",
      tab7.start_send(tab7.active_pane, recv_target,
                      {"path": "/in/box.bin", "name": "box.bin", "size": 3, "mtime": 0}) is False
      and i18n.t("sftp.send.busy", alias="beta") in msgs7, str(msgs7))
wait_until(lambda: not tab7._sends, timeout_ms=15000)
check("the file of the SOURCE pane landed in the target session's folder",
      fs_recv.files.get("/in/box.bin") == b"box", str(fs_recv.files.get("/in/box.bin")))
check("the pane's OWN conflict question was asked with both sides' facts (the container's seam)",
      bool(asked7) and asked7[0][1] == "/in" and "3 B" in asked7[0][2] and "23 B" in asked7[0][2],
      str(asked7))
check("the closing line names the target session and the folder",
      any(i18n.t("sftp.send.done", name="box.bin", alias="beta", dir="/in") in m for m in msgs7),
      str(msgs7[-3:]))
tab7.set_worker(None)
for _w in (send_worker, recv_worker, worker7):
    _w.shutdown(wait_ms=2000)
clear_cfg()

_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = FakeSSHThread
mw = MW.MainWindow()
mw.show()
app.processEvents()
node_a = mw.scene.add_server(ServerData(id="fs-a", alias="alpha", host="10.93.0.1", user="root"))
node_b = mw.scene.add_server(ServerData(id="fs-b", alias="beta", host="10.93.0.2", user="root"))
win_a = mw._spawn_terminal_window(node_a, password="pw")
page_a = win_a.session_tabs.widget(0)
win_b = mw._spawn_terminal_window(node_b, password="pw")
page_b = win_b.session_tabs.widget(0)
check("a session whose Files channel was never opened is not a TARGET (it has no transport)",
      mw._send_session_targets("") == [], str(mw._send_session_targets("")))
win_a.terminal_thread.client = FakeSSHClient(FakeSftpClient(FakeSftpFS()))
win_b.terminal_thread.client = FakeSSHClient(FakeSftpClient(FakeSftpFS()))
page_a.show_files_tab()
page_b.show_files_tab()
wait_until(lambda: getattr(page_a, "_sftp_worker", None) is not None
           and getattr(page_b, "_sftp_worker", None) is not None, timeout_ms=8000)
tab_a, tab_b = page_a.sftp_tab, page_b.sftp_tab
_targets_a = mw._send_session_targets(tab_a.session_key())
check("the provider offers the OTHER live session (its key, its worker, its directory)",
      len(_targets_a) == 1 and _targets_a[0].key == tab_b.session_key()
      and _targets_a[0].worker is page_b._sftp_worker and _targets_a[0].directory == "/"
      and _targets_a[0].label == "beta" and _targets_a[0].host == "10.93.0.2",
      str([(t.key, t.label) for t in _targets_a]))
check("...and never the sender itself", all(t.key != tab_a.session_key() for t in _targets_a))
check("the session key IS the `history_key()` of the server (ONE identity everywhere)",
      tab_a.session_key() == history_key(node_a.data.id)
      and tab_b.session_key() == history_key(node_b.data.id))
check("the two sessions share ONE host only when the host and the port really match",
      SEND.same_host(_targets_a[0], mw._send_session_targets(tab_b.session_key())[0]) is False)
page_a.shutdown()
page_b.shutdown()
win_a.close()
win_b.close()
mw.close()
app.processEvents()
ST.SSHTerminalThread = _orig_thread_cls

check_release_state(ROOT)
_langs = load_i18n_langs(ROOT)
check_i18n_parity(_langs)
check_i18n_format(_langs)
check("the release adds exactly the Files-surface keys (the relay, the memory, the drop, the wrap)",
      all(key in _langs["en"] for key in
          ("sftp.send.menu", "sftp.send.title", "sftp.send.progress", "sftp.send.done",
           "sftp.send.too_big", "sftp.conflict.facts", "sftp.dir_missing",
           "sftp.cmd.drop_same_pane", "sftp.cmd.drop_other_session",
           "sftp.viewer.word_wrap")))
check("this is the release the file describes and the project format did NOT move",
      releases_at_least(EXPECTED_APP_VERSION, "1.7.3")
      and __import__("version").VERSION_FORMAT == "0.9")

finish()
