# -*- coding: utf-8 -*-
"""The hardening patch of the 1.8.1 line (v1.8.1.1): the ONE atomic writer, the send identity, the spool and the two document guards.

Offscreen, NO network. §1 the atomic-write mechanism (`storage/atomic.py`): the writer family on it,
the concurrency invariant and the failed-write cleanup; §2 the send identity (`same_host()` over
`(host, ssh_port, user)`, the endpoint field, the dialog sentence and the two-user relay); §3 the
spool (`create_spool()`, the verified twin and the age sweep); §4 the guards of the batch; §5 the
release state. Ledger — `AUDIT_PENDING.md` (N51, N54, N59, N60, R8).
Run: python tests/test_hardening_v1811.py   (from the project root) or python tests/run_all.py"""
import json
import os
import shutil
import stat
import subprocess
import sys
import threading
import time

from _common import (bootstrap, check, finish, wait_until, clear_cfg, read_cfg, load_i18n_langs,
                     check_i18n_parity, check_i18n_format, check_release_state, releases_at_least,
                     EXPECTED_APP_VERSION)

ROOT, WORK = bootstrap()  # HOME isolation + offscreen Qt + sys.path (BEFORE any app import)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

import i18n  # noqa: E402
import modules.bookmarks as BKM  # noqa: E402
import modules.command_history as CH  # noqa: E402
import modules.host_key_policy as HKP  # noqa: E402
import modules.sftp_send as SEND  # noqa: E402
import storage.atomic as ATOMIC  # noqa: E402
import storage.autosave as ASAUTOSAVE  # noqa: E402
from modules.sftp_tab import SftpTab  # noqa: E402
from modules.sftp_worker import PART_SUFFIX, SftpWorker  # noqa: E402

from _fakes import EventLog, FakeSftpClient, FakeSftpFS, wire_worker  # noqa: E402

PROBE_NAMES = ("plant-me.bin", "folder-plant.bin", "linked.bin", "filled.bin", "young.bin")


def source_of(rel):
    """The text of one repository file (the structural pins read it)."""
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def tmp_files(folder):
    """The provisional files left in a folder (`*.tmp` — a failed write may leave NONE)."""
    try:
        return sorted(n for n in os.listdir(folder) if n.endswith(ATOMIC.TEMP_SUFFIX))
    except OSError:
        return []


def spool_leaks(tags=PROBE_NAMES):
    """The probe spools still sitting in the OS temp folder (the cleanup assertion)."""
    try:
        names = os.listdir(SEND.spool_dir())
    except OSError:
        return []
    return sorted(n for n in names
                  if n.startswith(SEND.SPOOL_PREFIX) and any(tag in n for tag in tags))


def age_file(path, seconds):
    """Push a file's mtime `seconds` into the past (the sweep's rule is an AGE, not a name)."""
    old = time.time() - float(seconds)
    os.utime(path, (old, old))


def one_worker(fs):
    """A started `SftpWorker` over one in-memory remote FS — no widget, no network."""
    client = FakeSftpClient(fs)
    client.copy_data_ok = False
    worker = SftpWorker(client)
    wire_worker(worker, EventLog())
    worker.start()
    return worker


# ════════════════════════════════════════════════════════════
# 1. N51 — the atomic write is a MECHANISM
# ════════════════════════════════════════════════════════════
print("== 1. N51: ONE atomic writer, the lock around the read-modify-write ==")

check("the mechanism is a module of its own (storage/atomic.py)",
      os.path.isfile(os.path.join(ROOT, "storage", "atomic.py")))
check("it owns the publish, the merge-write and the ONE lock per path",
      all(callable(getattr(ATOMIC, name, None)) for name in
          ("publish_atomic", "write_json_atomic", "atomic_lock", "read_json", "dump_json"))
      and ATOMIC.TEMP_SUFFIX == ".tmp" and isinstance(ATOMIC.TEMP_MODE, int))
check("the lock of ONE path is ONE object (every writer shares it, and it re-enters)",
      ATOMIC.atomic_lock("a/b.json") is ATOMIC.atomic_lock("a/b.json")
      and ATOMIC.atomic_lock("a/b.json") is not ATOMIC.atomic_lock("a/c.json"))

# The eight writers of the ledger's table, and which half of the mechanism each one needs.
_WRITER_SITES = (
    ("i18n/__init__.py", "write_json_atomic"),            # config.json — MERGE
    ("modules/bookmarks.py", "write_json_atomic"),        # bookmarks.json — merge-on-write
    ("modules/command_history.py", "write_json_atomic"),  # history/<key>.json — merge-on-write
    ("modules/command_library.py", "write_json_atomic"),  # commands.json — whole document
    ("models/profile.py", "publish_atomic"),              # profiles.json — RAISES to the caller
    ("storage/autosave.py", "publish_atomic"),            # autosave + the backup ring — RAISES
    ("storage/project.py", "publish_atomic"),             # the project file — RAISES
    ("modules/host_key_policy.py", "publish_atomic"),     # known_hosts — the same answer
)
_missing = [rel for rel, needle in _WRITER_SITES if needle not in source_of(rel)]
check("every writer of the family goes through `storage/atomic.py`", not _missing, _missing)
_fixed = [rel for rel, _needle in _WRITER_SITES
          if '+ ".tmp"' in source_of(rel) or "'.tmp'" in source_of(rel)]
check("no writer is left with its own FIXED `path + '.tmp'` provisional name", not _fixed, _fixed)
check("the cross-process answer has ONE home (the known_hosts store points, never restates)",
      "cross-process" in source_of("storage/atomic.py").lower()
      and "Cross-process writers are deliberately" not in source_of("modules/host_key_policy.py"))

_conc = os.path.join(WORK, "atomic_conc")
shutil.rmtree(_conc, ignore_errors=True)
os.makedirs(_conc)
_conc_path = os.path.join(_conc, "merged.json")
ATOMIC.write_json_atomic(_conc_path, {"existing": "KEEP-ME"})
_false = []
_WRITERS, _ROUNDS = 4, 20
_barrier = threading.Barrier(_WRITERS)


def _merger(n):
    _barrier.wait(timeout=20)
    for r in range(_ROUNDS):
        if not ATOMIC.write_json_atomic(_conc_path, {"t%d_k%d" % (n, r): r}, merge=True):
            _false.append((n, r))


_threads = [threading.Thread(target=_merger, args=(n,)) for n in range(_WRITERS)]
for _th in _threads:
    _th.start()
for _th in _threads:
    _th.join()
with open(_conc_path, encoding="utf-8") as _fh:
    _final = json.load(_fh)
_lost = [(n, r) for n in range(_WRITERS) for r in range(_ROUNDS)
         if "t%d_k%d" % (n, r) not in _final]
check("four concurrent merge-writers lose NOTHING and no call answers False (the ledger's probe)",
      not _lost and not _false and _final.get("existing") == "KEEP-ME"
      and len(_final) == 1 + _WRITERS * _ROUNDS,
      "lost=%d false=%d keys=%d" % (len(_lost), len(_false), len(_final)))
check("...and the whole run leaves no provisional file behind", tmp_files(_conc) == [],
      str(tmp_files(_conc)))

_blocked = os.path.join(WORK, "atomic_blocked")
shutil.rmtree(_blocked, ignore_errors=True)
os.makedirs(_blocked)
with open(os.path.join(_blocked, "not_a_folder"), "w", encoding="utf-8") as _fh:
    _fh.write("x")
_bad_path = os.path.join(_blocked, "not_a_folder", "config.json")
check("a write that cannot be published answers False and RAISES nothing",
      ATOMIC.write_json_atomic(_bad_path, {"a": 1}) is False and not os.path.exists(_bad_path))
check("...and the failed write leaves no `*.tmp` anywhere", tmp_files(_blocked) == [],
      str(tmp_files(_blocked)))

# The end-to-end merge probe of the ledger: `i18n.save_config()` itself, in threads.
clear_cfg()
i18n.save_config({"existing": "KEEP-ME", "language": "ru"})
_cfg_false = []
_cfg_barrier = threading.Barrier(4)


def _cfg_writer(n):
    _cfg_barrier.wait(timeout=20)
    for r in range(15):
        if not i18n.save_config({"cfg%d_%d" % (n, r): r}):
            _cfg_false.append((n, r))


_cfg_threads = [threading.Thread(target=_cfg_writer, args=(n,)) for n in range(4)]
for _th in _cfg_threads:
    _th.start()
for _th in _cfg_threads:
    _th.join()
_cfg = read_cfg({}) or {}
_cfg_lost = [(n, r) for n in range(4) for r in range(15) if "cfg%d_%d" % (n, r) not in _cfg]
check("`save_config()` keeps every concurrent merge (the same 0 lost / 0 False invariant)",
      not _cfg_lost and not _cfg_false and _cfg.get("existing") == "KEEP-ME"
      and _cfg.get("language") == "ru",
      "lost=%d false=%d keys=%d" % (len(_cfg_lost), len(_cfg_false), len(_cfg)))
check("...and the config folder holds no provisional file",
      tmp_files(os.path.dirname(i18n._CONFIG_FILE)) == [],
      str(tmp_files(os.path.dirname(i18n._CONFIG_FILE))))

# The SECOND merge-writer: four sessions of one node folding their own commands into ONE file.
_hist_dir = os.path.join(WORK, "history")
shutil.rmtree(_hist_dir, ignore_errors=True)
_store = CH.CommandHistoryStore("merge-node", directory=_hist_dir)
_hist_barrier = threading.Barrier(4)


def _hist_writer(n):
    writer = CH.CommandHistoryStore("merge-node", directory=_hist_dir)
    _hist_barrier.wait(timeout=20)
    for r in range(10):
        writer.record("echo t%dk%d" % (n, r), timestamp=1700000000 + r)


_hist_threads = [threading.Thread(target=_hist_writer, args=(n,)) for n in range(4)]
for _th in _hist_threads:
    _th.start()
for _th in _hist_threads:
    _th.join()
_cmds = {e["cmd"] for e in _store.load()}
_hist_lost = ["echo t%dk%d" % (n, r) for n in range(4) for r in range(10)
              if "echo t%dk%d" % (n, r) not in _cmds]
check("the command history folds 4 concurrent sessions into ONE file without losing a command",
      not _hist_lost and len(_cmds) == 40, "lost=%d commands=%d" % (len(_hist_lost), len(_cmds)))
check("...and a merge leaves no provisional file", tmp_files(_hist_dir) == [],
      str(tmp_files(_hist_dir)))
_merged_probe = _store.merge([{"cmd": "echo probe-merge", "last": 1700009999, "count": 1}])
check("...and a SUCCESSFUL merge answers the folded list it just wrote (the file agrees)",
      "echo probe-merge" in {e["cmd"] for e in _merged_probe}
      and _merged_probe == _store.load(),
      "merged=%d file=%d" % (len(_merged_probe), len(_store.load())))

# The COPY half of the mechanism: `shutil.copy2` carries the SOURCE's own mode, so a READ-ONLY
# source reaches the provisional file unwritable — `_fsync()` owns that case (the mode is put back
# before the publish, so a backup of a read-only project keeps the mode it came from).
_ro_dir = os.path.join(WORK, "atomic_readonly")
shutil.rmtree(_ro_dir, ignore_errors=True)
os.makedirs(_ro_dir)
_ro_src = os.path.join(_ro_dir, "project.json")
with open(_ro_src, "w", encoding="utf-8") as _fh:
    _fh.write('{"version": "0.9", "servers": []}')
os.chmod(_ro_src, 0o444)
_ro_mode = stat.S_IMODE(os.stat(_ro_src).st_mode)
_ro_dst = os.path.join(_ro_dir, "backup_001.json")
_ro_error = ""
try:
    ASAUTOSAVE._atomic_copy(_ro_src, _ro_dst)
except OSError as _e:  # the review's probe: the copy half of the mechanism, kept as a check
    _ro_error = repr(_e)
_ro_dst_mode = stat.S_IMODE(os.stat(_ro_dst).st_mode) if os.path.isfile(_ro_dst) else -1
_ro_bytes = ""
if os.path.isfile(_ro_dst):
    with open(_ro_dst, encoding="utf-8") as _fh:
        _ro_bytes = _fh.read()
check("a READ-ONLY source is COPIED (the fsync opens a writable handle and puts the mode back)",
      not _ro_error and _ro_bytes == '{"version": "0.9", "servers": []}'
      and _ro_dst_mode == _ro_mode,
      f"error={_ro_error} mode={oct(_ro_dst_mode)} wanted={oct(_ro_mode)}")
_ring_error = ""
_ring = []
try:
    _ring = ASAUTOSAVE.rotate_backups(_ro_src, 2)   # the shipped door of `MainWindow._do_save()`
except OSError as _e:
    _ring_error = repr(_e)
check("...and the BACKUP RING of a read-only project still rotates (the user-visible door)",
      not _ring_error and len(_ring) == 1, f"error={_ring_error} slots={len(_ring)}")
check("...and the read-only copy leaves no provisional file", tmp_files(_ro_dir) == [],
      str(tmp_files(_ro_dir)))
for _path in [_ro_src, _ro_dst] + [item["path"] for item in _ring]:
    try:
        os.chmod(_path, 0o644)
    except OSError:
        pass

# The SAME mechanism for the known_hosts store: one publish path, no `.tmp`, one answer.
_hk_dir = os.path.join(WORK, "hk")
os.makedirs(_hk_dir, exist_ok=True)
_hk_path = os.path.join(_hk_dir, "known_hosts")
check("the known_hosts store publishes through the mechanism and leaves no `.tmp`",
      HKP.KnownHostsStore(path=_hk_path).save() is True and os.path.isfile(_hk_path)
      and tmp_files(_hk_dir) == [], str(tmp_files(_hk_dir)))

_bm_path = os.path.join(WORK, "bm.json")
check("the bookmarks store writes its own document through the mechanism (no `.tmp` left)",
      BKM.BookmarkStore(path=_bm_path).save(
          [{"type": "url", "name": "wiki", "value": "https://example.invalid/"}]) is True
      and tmp_files(WORK) == [], str(tmp_files(WORK)))


# ════════════════════════════════════════════════════════════
# 2. N54 — a send is bound to the identity it was opened with
# ════════════════════════════════════════════════════════════
print("== 2. N54: `same_host()` reads the USER, and the dialog names it ==")

check("`SendEndpoint` carries the user (the field the comparison needs)",
      "user" in SEND.SendEndpoint.__slots__
      and SEND.SendEndpoint(host="h", user="root").user == "root"
      and SEND.SendEndpoint().user == "")
check("the SAME host, port AND user is the server-side path",
      SEND.same_host(SEND.SendEndpoint(host="h", port=22, user="root"),
                     SEND.SendEndpoint(host="H", port=22, user="root")) is True)
check("ONE host with TWO users is NOT the same end (root@h to alice@h must relay)",
      SEND.same_host(SEND.SendEndpoint(host="h", port=22, user="root"),
                     SEND.SendEndpoint(host="h", port=22, user="alice")) is False)
check("an UNKNOWN user is never 'the same' (the shipped rule for an unknown host)",
      SEND.same_host(SEND.SendEndpoint(host="h", port=22),
                     SEND.SendEndpoint(host="h", port=22)) is False
      and SEND.same_host(SEND.SendEndpoint(host="h", port=22, user="root"),
                         SEND.SendEndpoint(host="h", port=22)) is False)
check("a different port or host still takes the relay",
      SEND.same_host(SEND.SendEndpoint(host="h", user="root"),
                     SEND.SendEndpoint(host="h", port=2222, user="root")) is False
      and SEND.same_host(SEND.SendEndpoint(host="h", port=22, user="root"),
                         SEND.SendEndpoint(host="g", port=22, user="root")) is False)

_tab = SftpTab()
_tab.set_session_info(key="k", label="alpha", host="10.0.0.1", port=22, user="root")
check("the container's SOURCE endpoint carries the session's login user",
      _tab._source_endpoint(None).user == "root")
check("the window's target provider hands the node's user to `endpoint_from_tab()`",
      'user=getattr(data, "user"' in source_of("ui/main_window_ssh.py")
      and "user" in SEND.endpoint_from_tab.__code__.co_varnames)

_target = SEND.SendEndpoint(host="10.0.0.1", port=22, user="root", directory="/out")
_entry = {"path": "/in/a.bin", "name": "a.bin", "size": 3, "mtime": 0}
_dialog_same = SEND.SendFileDialog(None, _entry, _target, same_host=True, user="root")
check("the dialog says WHOM the server-side copy runs as (ONE sentence, the new key)",
      _dialog_same.user_note is not None
      and _dialog_same.user_note.text() == i18n.t("sftp.send.same_host_user_note", user="root"),
      _dialog_same.user_note.text() if _dialog_same.user_note is not None else "None")
_dialog_relay = SEND.SendFileDialog(None, _entry, _target, same_host=False, user="root")
check("...and says nothing of the sort on the relay path (the sentence belongs to that path)",
      _dialog_relay.user_note is None)
_dialog_same.deleteLater()
_dialog_relay.deleteLater()

# End to end: ONE host, TWO users — the relay runs and the bytes arrive through the spool.
_fs_two = FakeSftpFS()
_fs_two.add_dir("/in")
_fs_two.add_dir("/out")
_fs_two.add_file("/in/two.bin", b"payload" * 512)
_src_worker = one_worker(_fs_two)
_dst_worker = one_worker(_fs_two)
_relay = SEND.SendRelay(
    SEND.SendEndpoint(key="r1", host="one-host", port=22, user="root",
                      worker=_src_worker, directory="/in"),
    SEND.SendEndpoint(key="r2", host="one-host", port=22, user="alice",
                      worker=_dst_worker, directory="/out"),
    {"path": "/in/two.bin", "name": "two.bin", "size": 7 * 512, "mtime": 0})
_relay_results = []
_relay.finished.connect(_relay_results.append)
_relay.start("/out")
check("one host with two users takes the RELAY strategy (never the source user's `queue_copy`)",
      _relay.strategy == SEND.SEND_STRATEGY_RELAY and _relay.spool != "",
      "strategy=%s" % _relay.strategy)
wait_until(lambda: _relay_results, timeout_ms=20000)
check("...and the file crosses byte for byte through the spool",
      bool(_relay_results) and _relay_results[0]["ok"] is True
      and _fs_two.files.get("/out/two.bin") == b"payload" * 512,
      str(_relay_results[:1]))
check("...and the spool is gone once the send is over",
      bool(_relay.spool) and not os.path.exists(_relay.spool)
      and not os.path.exists(_relay.spool + PART_SUFFIX))
_src_worker.shutdown(wait_ms=3000)
_dst_worker.shutdown(wait_ms=3000)


# ════════════════════════════════════════════════════════════
# 3. N59 — the spool stops being plantable and stops killing its neighbours
# ════════════════════════════════════════════════════════════
print("== 3. N59: `mkstemp`, the verified twin and the age sweep ==")

_spool_a = SEND.create_spool("plant-me.bin")
_spool_b = SEND.create_spool("plant-me.bin")
check("a spool is created under a name nobody could have claimed (`mkstemp`, unique)",
      bool(_spool_a) and bool(_spool_b) and _spool_a != _spool_b
      and os.path.basename(_spool_a).startswith(SEND.SPOOL_PREFIX)
      and os.path.isfile(_spool_a))
if os.name == "posix":
    check("...and the created spool carries the declared tight mode (0600)",
          (os.stat(_spool_a).st_mode & 0o777) == SEND.SPOOL_FILE_MODE,
          oct(os.stat(_spool_a).st_mode & 0o777))
check("a FREE twin name is claimed exclusively (the shipped answer is True)",
      SEND.prepare_spool(_spool_a) is True and os.path.isfile(_spool_a + PART_SUFFIX))

_folder_twin = SEND.create_spool("folder-plant.bin")
os.makedirs(_folder_twin + PART_SUFFIX, exist_ok=True)
check("a twin that is a FOLDER is refused (it is not the provisional file of any send)",
      SEND.prepare_spool(_folder_twin) is False)
os.rmdir(_folder_twin + PART_SUFFIX)

_victim = os.path.join(WORK, "victim.txt")
with open(_victim, "w", encoding="utf-8") as _fh:
    _fh.write("IMPORTANT USER DATA")
_linked = SEND.create_spool("linked.bin")
try:
    os.link(_victim, _linked + PART_SUFFIX)
    _link_made = True
except (OSError, NotImplementedError, AttributeError):
    _link_made = False
if _link_made:
    with open(_victim, encoding="utf-8") as _fh:
        _victim_text = _fh.read()
    check("a HARD LINK planted at the twin name is refused (the victim file is never opened)",
          SEND.prepare_spool(_linked) is False and _victim_text == "IMPORTANT USER DATA"
          and os.lstat(_linked + PART_SUFFIX).st_nlink == 2,
          "nlink=%d" % os.lstat(_linked + PART_SUFFIX).st_nlink)
    os.remove(_linked + PART_SUFFIX)

_filled = SEND.create_spool("filled.bin")
with open(_filled + PART_SUFFIX, "w", encoding="utf-8") as _fh:
    _fh.write("somebody else's bytes")
check("a twin that already HOLDS BYTES is refused (ours is created empty and stays empty)",
      SEND.prepare_spool(_filled) is False)

_sweep_dir = os.path.join(WORK, "spool_sweep")
shutil.rmtree(_sweep_dir, ignore_errors=True)
os.makedirs(_sweep_dir)
_old = os.path.join(_sweep_dir, SEND.SPOOL_PREFIX + "1111-1-old.bin")
_young = os.path.join(_sweep_dir, SEND.SPOOL_PREFIX + "2222-2-young.bin")
for _path in (_old, _young, _old + PART_SUFFIX):
    with open(_path, "wb") as _fh:
        _fh.write(b"")
age_file(_old, SEND.SPOOL_MAX_AGE_SEC + 120)
age_file(_old + PART_SUFFIX, SEND.SPOOL_MAX_AGE_SEC + 120)
check("the sweep takes the OLD spool (and its twin) and never touches a LIVE one",
      SEND.sweep_spools(_sweep_dir, max_age_sec=SEND.SPOOL_MAX_AGE_SEC) == 2
      and not os.path.exists(_old) and not os.path.exists(_old + PART_SUFFIX)
      and os.path.exists(_young),
      "old=%s young=%s" % (os.path.exists(_old), os.path.exists(_young)))
check("the age rule is DECLARED and is a parameter of the sweep (never a magic number)",
      isinstance(SEND.SPOOL_MAX_AGE_SEC, (int, float)) and SEND.SPOOL_MAX_AGE_SEC > 0
      and "max_age_sec" in SEND.sweep_spools.__code__.co_varnames)
check("a YOUNG spool survives a sweep with the default age (a sibling instance is untouched)",
      SEND.sweep_spools(_sweep_dir) == 0 and os.path.exists(_young))

for _path in (_spool_a, _spool_b, _folder_twin, _linked, _filled):
    SEND.drop_spool(_path)
check("the section leaves no probe spool in the OS temp folder", spool_leaks() == [],
      str(spool_leaks()))


# ════════════════════════════════════════════════════════════
# 4. N60 / R8 — the two document guards of the batch
# ════════════════════════════════════════════════════════════
print("== 4. N60 / R8: the repository's closed world and the rollover pin ==")

_docs_src = source_of("tests/test_docs.py")
check("the tracked/ignored cross-check lives in tests/test_docs.py (AUDIT N60)",
      "every *.md named by .gitignore is UNTRACKED" in _docs_src and "ls-files" in _docs_src)
check("the details-migration pin is the FIVE historical lines (AUDIT R8)",
      '_DETAILS_MIGRATION_LINES = {"0997", "114", "1214", "1338", "147"}' in _docs_src
      and "the PINNED migration set" in _docs_src)


def _git(args):
    """(returncode, stdout) of one git call; (None, "") when git is missing or unusable."""
    try:
        done = subprocess.run(["git"] + list(args), cwd=ROOT, capture_output=True, text=True,
                              timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None, ""
    return (None, done.stdout or "") if done.returncode != 0 else (done.returncode, done.stdout or "")


with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as _fh:
    _ignored_md = sorted({ln.strip() for ln in _fh
                          if ln.strip().endswith(".md") and not ln.strip().startswith("#")})
_code, _out = _git(["ls-files"])
if _code is None:
    print("  note  git is unavailable — the tracked/ignored cross-check is skipped here")
else:
    _tracked = {ln.strip().replace("\\", "/") for ln in _out.splitlines() if ln.strip()}
    _published = sorted(name for name in _ignored_md if name in _tracked)
    check("no internal `*.md` of .gitignore is TRACKED (the ignore list answers §13)",
          not _published, _published)
    check("...and the check really reads the ignore list", len(_ignored_md) >= 5, str(_ignored_md))


# ════════════════════════════════════════════════════════════
# 5. The release state
# ════════════════════════════════════════════════════════════
print("== 5. the release state ==")

check_release_state(ROOT)
_langs = load_i18n_langs(ROOT)
check_i18n_parity(_langs)
check_i18n_format(_langs)
check("the patch adds exactly ONE dialog key (the identity sentence of task 2)",
      all("sftp.send.same_host_user_note" in _langs[code] for code in _langs))
check("this is the release the file describes and the project format did NOT move",
      releases_at_least(EXPECTED_APP_VERSION, "1.8.1.1")
      and __import__("version").VERSION_FORMAT == "0.9")

finish()
