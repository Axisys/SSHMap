# -*- coding: utf-8 -*-
"""The ELEVATED Files pane (v1.8): the sudo command table and its allowlist, the handshake over a
fake transport and a fake `sftp-server`, the provider swap of the second Commander pane, the ONE
refusal of every write door and the teardown.

Offscreen, no network: the elevated `SFTPClient` is the fake surface of `_fakes.py` and the
transport is a scripted stand-in for a paramiko one, so no channel is ever opened.
Contract — `ELEVATED_PANE.md` §1–§7; mechanism — `DOCUMENTATION.md` §70.
Run: python tests/test_elevated_pane.py   (from the project root) or python tests/run_all.py"""
import os
import sys

from _common import (bootstrap, check, finish, wait_for, check_i18n_parity, check_i18n_format,
                     check_release_state, clear_cfg, load_i18n_langs, EXPECTED_I18N_KEYS)

ROOT, WORK = bootstrap()  # BEFORE the app imports (the HOME isolation)

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

import i18n
import modules.sftp_elevated as ELEV
import modules.sftp_tab as STAB
from modules.sftp_tab import (SOURCE_ELEVATED, SOURCE_LOCAL, SOURCE_REMOTE, SftpTab, _SourceSwitch)
from modules.sftp_worker import KIND_COPY, KIND_MKDIR, KIND_MOVE, SftpWorker

from _fakes import EventLog, FakeSftpClient, FakeSftpFS, wire_worker


# ════════════════════════════════════════════════════════════
# The fakes: a scripted transport, its channels and the client
# ════════════════════════════════════════════════════════════

class FakeChannel:
    """One session channel: its command, the scripted answer, its stderr stream and its stdin."""

    def __init__(self, transport):
        self._transport = transport
        self.command = ""
        self.status = 0
        self.stderr = b""
        self.sftp = True
        self.stdin = b""
        self.closed = False

    def exec_command(self, command):
        self.command = str(command)
        self.status, self.stderr, self.sftp = self._transport.answer(self.command)

    def sendall(self, data):
        self.stdin += bytes(data)

    def exit_status_ready(self):
        return True

    def recv_exit_status(self):
        return self.status

    def recv_stderr_ready(self):
        return bool(self.stderr)

    def recv_stderr(self, _n=4096):
        return self.stderr

    def close(self):
        self.closed = True


class FakeTransport:
    """A paramiko Transport stand-in: a COMMAND PREFIX decides what its channel answers."""

    def __init__(self, rules=None, active=True):
        self.rules = list(rules or [])
        self.active = active
        self.channels = []

    def is_active(self):
        return bool(self.active)

    def answer(self, command):
        """`(exit status, stderr, the channel really speaks SFTP)` of one command."""
        for prefix, status, stderr, sftp in self.rules:
            if str(command).startswith(prefix):
                return status, stderr, sftp
        return 0, b"", True

    def open_session(self):
        channel = FakeChannel(self)
        self.channels.append(channel)
        return channel

    def commands(self):
        return [ch.command for ch in self.channels]


class FakeParamiko:
    """The `paramiko` module attribute as the handshake reads it (the substitution seam)."""

    def __init__(self, client=None, error=None):
        self.client = client
        self.error = error
        self.calls = []

    def SFTPClient(self, channel):   # noqa: N802 — the paramiko name
        self.calls.append(channel)
        if self.error is not None and not getattr(channel, "sftp", True):
            raise self.error
        return self.client


class FakeHandshake(QObject):
    """The pane-side handshake seam: it records its arguments and answers on demand."""

    ready = Signal(object, str)
    failed = Signal(str, str)

    def __init__(self, transport, user="", password="", parent=None):
        super().__init__(parent)
        self.transport = transport
        self.user = user
        self.password = password
        self.started = False
        self.closed = False
        self.stopped = False
        self.deleted = False

    def start(self):
        self.started = True

    def isRunning(self):
        return False

    def close(self):
        self.closed = True

    def shutdown(self, wait_ms=0):
        self.stopped = True

    def deleteLater(self):   # noqa: N802 — the Qt name
        self.deleted = True


def make_tab(fs=None, commander=True, key="sess-1"):
    """(tab, worker, log) — a Files tab over the fake SFTP surface, two panes by default."""
    fs = fs or FakeSftpFS()
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
    tab.set_session_info(key=key, label="prod", host="10.0.0.5", port=22, user="root")
    return tab, worker, log


def rows(pane):
    return [pane.tree.topLevelItem(i).text(0) for i in range(pane.tree.topLevelItemCount())]


def item_named(pane, name):
    for i in range(pane.tree.topLevelItemCount()):
        item = pane.tree.topLevelItem(i)
        if item.text(0) == name:
            return item
    return None


def run_handshake(transport, user="admin", password="", client=None, error=None):
    """Drive ONE handshake synchronously: (the answers, the object, the fake paramiko)."""
    fake = FakeParamiko(client, error)
    original = ELEV.paramiko
    ELEV.paramiko = fake
    answers = {"ready": [], "failed": []}
    handshake = ELEV.ElevatedHandshake(transport, user, password)
    handshake.ready.connect(lambda c, d: answers["ready"].append((c, d)))
    handshake.failed.connect(lambda c, d: answers["failed"].append((c, d)))
    try:
        handshake.run()
    finally:
        ELEV.paramiko = original
    return answers, handshake, fake


clear_cfg()   # the sandbox config: no remembered Commander state of a previous run

_fs = FakeSftpFS()
_fs.add_dir("/root")
_fs.add_file("/root/secret.txt", b"top secret\n")
_ok_client = FakeSftpClient(_fs)

# A transport where the FIRST candidate is refused and every LATER one is permitted.
_second_ok = [(ELEV.elevated_probe_command("admin", ELEV.SFTP_SERVER_CANDIDATES[0]),
               1, b"sudo: a password is required\n", True)]


# ════════════════════════════════════════════════════════════
print("== §1 the command table and the allowlist (ELEVATED_PANE.md §2) ==")
# ════════════════════════════════════════════════════════════

check("§2 the candidate list is ONE declared tuple of absolute server paths, the Debian one first",
      isinstance(ELEV.SFTP_SERVER_CANDIDATES, tuple)
      and len(ELEV.SFTP_SERVER_CANDIDATES) >= 3
      and ELEV.SFTP_SERVER_CANDIDATES[0] == "/usr/lib/openssh/sftp-server"
      and all(str(p).startswith("/") and "sftp-server" in str(p)
              for p in ELEV.SFTP_SERVER_CANDIDATES),
      str(ELEV.SFTP_SERVER_CANDIDATES))

check("§2 `root` (and an empty user) needs no `-u`, another user gets one",
      ELEV.sudo_prefix("") == "sudo -n" and ELEV.sudo_prefix("root") == "sudo -n"
      and ELEV.sudo_prefix("admin") == "sudo -n -u admin")

check("§2 the server command, the pre-flight probe and the prime are built by the ONE table",
      ELEV.elevated_server_command("root", "/usr/libexec/sftp-server")
      == "sudo -n /usr/libexec/sftp-server"
      and ELEV.elevated_server_command("admin", "/usr/lib/openssh/sftp-server")
      == "sudo -n -u admin /usr/lib/openssh/sftp-server"
      and ELEV.elevated_probe_command("admin", "/usr/lib/openssh/sftp-server")
      == "sudo -n -u admin -l /usr/lib/openssh/sftp-server"
      and ELEV.sudo_prime_command() == "sudo -S -v")

check("§2 the target user is ALLOWLISTED, and a leading `-` can never become an option",
      ELEV.user_problem("") is None and ELEV.user_problem("root") is None
      and ELEV.user_problem("admin-1.x") is None and ELEV.user_problem("_svc") is None
      and ELEV.user_problem("-evil") == "option" and ELEV.user_problem("a;b") == "characters"
      and ELEV.user_problem("a b") == "characters" and ELEV.user_problem("a$b") == "characters"
      and ELEV.user_problem("a" * 40) == "characters",
      str([ELEV.user_problem(v) for v in ("", "root", "-evil", "a;b", "a" * 40)]))

check("§2 every machine code has ONE declared sentence key, all in the sftp.elevated family",
      set(ELEV.ELEVATED_ERROR_KEYS) == {ELEV.ELEVATED_NO_TRANSPORT, ELEV.ELEVATED_PASSWORD,
                                        ELEV.ELEVATED_REFUSED, ELEV.ELEVATED_OPEN_FAILED,
                                        ELEV.ELEVATED_FAILED}
      and all(k.startswith("sftp.elevated.") for k in ELEV.ELEVATED_ERROR_KEYS.values()))

check("§2 a refusal detail is ONE bounded, folded line (never a multi-line dump)",
      ELEV.short_detail("  a\n\nb\tc  ") == "a b c"
      and len(ELEV.short_detail("x" * 500)) == ELEV.ELEVATION_DETAIL_CHARS)

_LANGS = load_i18n_langs(ROOT)
_ELEVATED_KEYS = sorted(k for k in _LANGS["en"] if k.startswith("sftp.elevated."))
check("§2 the sentences of every code exist in ALL the language files",
      len(_ELEVATED_KEYS) >= 15
      and all(str(_LANGS[code].get(key) or "").strip()
              for code in _LANGS for key in ELEV.ELEVATED_ERROR_KEYS.values()),
      str(_ELEVATED_KEYS))


# ════════════════════════════════════════════════════════════
print("== §2 the handshake over a fake transport (ELEVATED_PANE.md §2) ==")
# ════════════════════════════════════════════════════════════

_t1 = FakeTransport(rules=_second_ok + [(ELEV.elevated_probe_command(
    "admin", ELEV.SFTP_SERVER_CANDIDATES[1]), 0, b"", True)])
_answers, _hs, _fake = run_handshake(_t1, client=_ok_client)
check("§2 a PERMITTED candidate is really opened, wrapped and answered with its start directory",
      len(_answers["ready"]) == 1 and _answers["ready"][0][0] is _ok_client
      and _answers["ready"][0][1] == "/" and not _answers["failed"],
      f"ready={len(_answers['ready'])} failed={_answers['failed']}")
check("§2 ...the refused candidate was skipped and the permitted one really ran",
      _t1.commands()[0] == ELEV.elevated_probe_command("admin", ELEV.SFTP_SERVER_CANDIDATES[0])
      and ELEV.elevated_server_command("admin", ELEV.SFTP_SERVER_CANDIDATES[1]) in _t1.commands(),
      str(_t1.commands()))
check("§2 ...and every channel of the handshake is closed on the way out, the SERVER's own except",
      all(ch.closed for ch in _t1.channels
          if ch.command != ELEV.elevated_server_command("admin", ELEV.SFTP_SERVER_CANDIDATES[1]))
      and not _t1.channels[-1].closed,
      str([(ch.command, ch.closed) for ch in _t1.channels]))

_t2 = FakeTransport(rules=[("sudo -n -l", 1, b"sudo: a password is required\n", True)])
_answers2, _hs2, _fake2 = run_handshake(_t2, user="root", client=_ok_client)
check("§2 no candidate permitted → ONE `refused` answer carrying the server's own words",
      not _answers2["ready"] and len(_answers2["failed"]) == 1
      and _answers2["failed"][0][0] == ELEV.ELEVATED_REFUSED
      and "password is required" in _answers2["failed"][0][1],
      str(_answers2["failed"]))
check("§2 ...and every candidate was asked before the refusal",
      sum(1 for ch in _t2.channels if "-l " in ch.command) == len(ELEV.SFTP_SERVER_CANDIDATES)
      and all(ch.closed for ch in _t2.channels),
      str(_t2.commands()))

_answers3, _hs3, _ = run_handshake(FakeTransport(active=False), client=_ok_client)
check("§2 a session without a live transport answers `no_transport` and opens nothing",
      _answers3["failed"] == [(ELEV.ELEVATED_NO_TRANSPORT, "")], str(_answers3["failed"]))

_t4 = FakeTransport(rules=[("sudo -S -v", 1, b"Sorry, try again.\n", True)])
_answers4, _hs4, _ = run_handshake(_t4, password="hunter2", client=_ok_client)
check("§2 a refused password answers `password` with sudo's own text — never the secret",
      _answers4["failed"] and _answers4["failed"][0][0] == ELEV.ELEVATED_PASSWORD
      and "hunter2" not in str(_answers4["failed"]) and "try again" in _answers4["failed"][0][1],
      str(_answers4["failed"]))
check("§2 ...the prime ran on its OWN channel, before any probe, with the password on STDIN",
      _t4.channels[0].command == "sudo -S -v" and _t4.channels[0].stdin == b"hunter2\n"
      and all("-l " not in ch.command for ch in _t4.channels),
      str([(ch.command, ch.stdin) for ch in _t4.channels[:2]]))

_t5 = FakeTransport(rules=[("sudo -S -v", 0, b"", True)] + _second_ok)
_answers5, _hs5, _ = run_handshake(_t5, password="hunter2", client=_ok_client)
check("§2 ...and a good password lets the probe run on the refreshed timestamp",
      not _answers5["failed"] and _answers5["ready"]
      and _t5.channels[0].command == "sudo -S -v"
      and any("-l " in ch.command for ch in _t5.channels),
      str(_t5.commands()))

# A candidate allowed by sudo whose own subsystem never answers: the client constructor raises.
_broken = FakeTransport(rules=[("sudo -n -u admin /", 0, b"", False)])
_answers6, _hs6, _fake6 = run_handshake(_broken, client=_ok_client, error=Exception("EOF during negotiation"))
check("§2 a permitted path whose subsystem never answers falls through to the NEXT candidate",
      _answers6["failed"] and _answers6["failed"][0][0] == ELEV.ELEVATED_REFUSED
      and "EOF" in _answers6["failed"][0][1]
      and len(_fake6.calls) >= 2,
      f"failed={_answers6['failed']} calls={len(_fake6.calls)}")

check("§2 the thread keeps NO secret after the attempt (AGENTS.md §4.4)",
      _hs4._password == "" and _hs5._password == "" and _hs._password == "")
check("§2 ...and the client it HANDS OVER is not the one its own close() would close",
      _hs._client is None and _hs._channel is None
      and (_hs.close() or True) and not getattr(_ok_client, "_closed", False))


# ════════════════════════════════════════════════════════════
print("== §3 the pane: the third position of the source switch (ELEVATED_PANE.md §1, §4) ==")
# ════════════════════════════════════════════════════════════

_msgs = []
_tab, _worker, _log = make_tab()
_pane_a, _pane_b = _tab.panes[0], _tab.panes[1]
for _p in (_pane_a, _pane_b):
    _p.message.connect(_msgs.append)

check("§1 the elevated token is a THIRD position of the CONTROL and NOT a third data source",
      SOURCE_ELEVATED == "elevated" and STAB.PANE_SOURCES == (SOURCE_REMOTE, SOURCE_LOCAL)
      and isinstance(_pane_b.source_switch, _SourceSwitch)
      and _pane_b.source_switch.btn_elevated.text() == i18n.t("sftp.elevated.button"))

check("§4 the switch offers the elevation on the SECOND pane alone (the local pane's rule)",
      _tab.can_elevate(_pane_b) is True and _tab.can_elevate(_pane_a) is False
      and _tab.can_elevate(None) is False)

_single_tab, _single_worker, _ = make_tab(commander=False)
_single_msgs = []
_single_pane = _single_tab.panes[0]
_single_pane.message.connect(_single_msgs.append)
_single_tab.set_transport(FakeTransport())
STAB.ask_elevation = lambda parent, current: ("admin", "")
check("§4 a single-pane view of a session cannot elevate (nothing to sit BESIDE)",
      _single_tab.can_elevate(_single_pane) is False
      and _single_pane.begin_elevation(notify=True) is False
      and _single_msgs[-1:] == [i18n.t("sftp.elevated.unavailable")],
      str(_single_msgs[-2:]))

check("§4 with no transport the ask is refused with ONE sentence and nothing is elevated",
      _tab.set_transport(None) is None and _pane_b.begin_elevation(notify=True) is False
      and _msgs[-1:] == [i18n.t("sftp.elevated.no_transport")]
      and _pane_b.elevated is False and _pane_b._elevation_pending is False,
      str(_msgs[-2:]))

_transport = FakeTransport()
_tab.set_transport(_transport)
_asked = []


def _ask(parent, current):
    _asked.append(current)
    return ("admin", "hunter2")


STAB.ask_elevation = _ask
STAB.ElevatedHandshake = FakeHandshake

check("§4 the switch to Elevated starts the handshake and does NOT elevate yet",
      _tab.set_pane_source(_pane_b, SOURCE_ELEVATED) is True
      and _pane_b._elevation_pending is True and _pane_b.elevated is False
      and _pane_b._switch_state() == SOURCE_ELEVATED
      and _pane_b.source == SOURCE_REMOTE
      and i18n.t("sftp.elevated.working", user="admin") in _msgs,
      f"state={_pane_b._switch_state()!r} source={_pane_b.source!r}")

_handshake = _pane_b._handshake
check("§4 ...the handshake got the transport, the user and the password the dialogue answered",
      isinstance(_handshake, FakeHandshake) and _handshake.transport is _transport
      and _handshake.user == "admin" and _handshake.password == "hunter2"
      and _handshake.started is True)

_handshake.ready.emit(_ok_client, "/root")
check("§1 when it answers, the pane binds the SHIPPED engine over the elevated client",
      _pane_b.elevated is True and _pane_b._elevation_pending is False
      and isinstance(_pane_b._elevated_provider, SftpWorker)
      and _pane_b._elevated_provider is _pane_b.provider
      and _pane_b._elevated_client is _ok_client and _pane_b._handshake is None
      and _pane_b.source == SOURCE_REMOTE and _pane_b._elevation_user == "admin",
      f"provider={type(_pane_b.provider).__name__} source={_pane_b.source!r}")
check("§1 ...and the first pane of the SAME container is untouched by it",
      _pane_a.elevated is False and _pane_a.provider is _worker
      and _pane_a._elevated_provider is None)

check("§3 the elevated pane LISTS through the other user's client",
      wait_for(lambda: "secret.txt" in rows(_pane_b), timeout_ms=5000), str(rows(_pane_b)))
check("§3 ...and its header line NAMES the elevation (the local pane's rule)",
      _pane_b.header_text() == i18n.t("sftp.elevated.header", user="admin"),
      _pane_b.header_text())
check("§3 ...and the address bar keeps the shipped wording (the directory, never the source)",
      _pane_b.path_label.text() == _pane_b.current_dir == "/root",
      f"bar={_pane_b.path_label.text()!r} dir={_pane_b.current_dir!r}")

_cancel_tab, _cancel_worker, _ = make_tab()
_cancel_pane = _cancel_tab.panes[1]
_cancel_tab.set_transport(FakeTransport())
STAB.ask_elevation = lambda parent, current: None
check("§4 a cancelled dialogue changes nothing at all",
      _cancel_tab.set_pane_source(_cancel_pane, SOURCE_ELEVATED) is False
      and _cancel_pane.elevated is False and _cancel_pane._handshake is None
      and _cancel_pane._switch_state() == SOURCE_REMOTE
      and _cancel_pane.source_switch.source() == SOURCE_REMOTE)

_bad_tab, _bad_worker, _ = make_tab()
_bad_msgs = []
_bad_pane = _bad_tab.panes[1]
_bad_pane.message.connect(_bad_msgs.append)
_bad_tab.set_transport(FakeTransport())
STAB.ask_elevation = lambda parent, current: ("-evil", "")
check("§4 a user the allowlist refuses is said in ONE sentence and opens NO channel",
      _bad_pane.begin_elevation(notify=True) is False and _bad_pane._handshake is None
      and _bad_pane._elevation_pending is False
      and _bad_msgs[-1:] == [i18n.t("sftp.elevated.bad_user", user="-evil")]
      and _bad_pane._switch_state() == SOURCE_REMOTE,
      str(_bad_msgs[-2:]))

_fail_msgs = []
_fail_tab, _fail_worker, _ = make_tab()
_fail_pane = _fail_tab.panes[1]
_fail_pane.message.connect(_fail_msgs.append)
_fail_tab.set_transport(FakeTransport())
STAB.ask_elevation = _ask
_fail_tab.set_pane_source(_fail_pane, SOURCE_ELEVATED)
_fail_pane._handshake.failed.emit(ELEV.ELEVATED_REFUSED, "sudo: no tty present")
check("§6 a failed handshake is ONE translated sentence of the code table and elevates nothing",
      _fail_msgs[-1:] == [i18n.t("sftp.elevated.refused", error="sudo: no tty present")]
      and _fail_pane.elevated is False and _fail_pane._elevation_pending is False
      and _fail_pane._switch_state() == SOURCE_REMOTE,
      str(_fail_msgs[-1:]))
check("§6 ...and the sentence of an unknown code is empty (a foreign code is never shown raw)",
      _fail_pane.elevation_sentence("nonsense", "x") == "")


# ════════════════════════════════════════════════════════════
print("== §4 the read-only surface and its ONE refusal (ELEVATED_PANE.md §3, §5) ==")
# ════════════════════════════════════════════════════════════

STAB.ask_elevation = _ask
_read_only = i18n.t("sftp.elevated.read_only")
_write_msgs = []
_pane_b.message.connect(_write_msgs.append)

_pane_b._on_upload()
check("§5 the Upload button refuses with the ONE sentence and queues nothing",
      _write_msgs[-1:] == [_read_only] and not _pane_b._own_transfers
      and _pane_b._op_tasks == {}, str(_write_msgs[-1:]))

_pane_b._op_new_folder()
check("§5 NEW FOLDER is refused the same way", _write_msgs[-1:] == [_read_only])
_item = item_named(_pane_b, "secret.txt")
_pane_b._op_rename(_item)
check("§5 RENAME is refused the same way", _write_msgs[-1:] == [_read_only])
_pane_b._op_delete(_item)
check("§5 DELETE is refused BEFORE the confirmation (the question is never asked)",
      _write_msgs[-1:] == [_read_only] and _pane_b._op_tasks == {})

_pane_b._queue_transfer_batch([("/root/secret.txt", "secret.txt", 11)], KIND_COPY, "/tmp", set())
check("§5 a copy with the elevated pane as its SOURCE is refused and queues nothing",
      _write_msgs[-1:] == [_read_only] and _pane_b._op_batches == {}
      and _pane_b._batches == {}, str(_write_msgs[-1:]))

_pane_b._queue_transfer_batch([("/etc/passwd", "passwd", 1)], KIND_MOVE, "/root", set(),
                              _pane_b)
check("§5 a move INTO the elevated pane is refused the same way",
      _write_msgs[-1:] == [_read_only] and _pane_b._batches == {})

_f5_msgs = []
_pane_b.message.connect(_f5_msgs.append)
_pane_b.tree.setCurrentItem(_item)
_pane_b._remote_batch(KIND_COPY, _pane_a)
check("§5 the F5/F6 batch of a row of the elevated pane is refused too (ONE sentence)",
      _f5_msgs[-1:] == [_read_only], str(_f5_msgs[-1:]))

_drop_msgs = []
_pane_a.message.connect(_drop_msgs.append)
_pane_a._on_pane_drop({"session": _pane_a.session_key(), "pane": id(_pane_b),
                       "path": "/root/secret.txt", "source": SOURCE_REMOTE, "size": 11}, None)
check("§5 a row DRAGGED OUT of the elevated pane is refused (the payload names the source pane)",
      _drop_msgs[-1:] == [_read_only], str(_drop_msgs[-1:]))
check("§5 ...and the payload of an ORDINARY pane is not refused by that rule",
      _pane_a._elevated_drop_refused({"pane": id(_pane_a)}) is False
      and _pane_a._elevated_drop_refused({}) is False)

_explorer = [os.path.join(WORK, "upload.txt")]
with open(_explorer[0], "w", encoding="utf-8") as _fh:
    _fh.write("x\n")
_pane_b._on_drop(_explorer, _pane_b.current_dir)
check("§5 a drop of files ONTO the elevated pane is refused before anything is queued",
      _write_msgs[-1:] == [_read_only] and _pane_b._op_tasks == {}, str(_write_msgs[-1:]))

_write_msgs.clear()
_pane_b._queue_downloads([_item], WORK)
check("§3 a DOWNLOAD is a READ path and IS offered (it writes on THIS computer, not as the user)",
      wait_for(lambda: bool(_pane_b._own_transfers), timeout_ms=3000)
      and _write_msgs == [],
      f"msgs={_write_msgs} own={_pane_b._own_transfers}")
check("§3 ...and the elevated pane's own transfer is remembered by the pane (the Cancel rule)",
      bool(_pane_b._own_transfers))


# ════════════════════════════════════════════════════════════
print("== §5 the lifetime and the teardown (ELEVATED_PANE.md §4) ==")
# ════════════════════════════════════════════════════════════

_switch_msgs = []
_pane_b.message.connect(_switch_msgs.append)
check("§4 a switch BACK to Server drops the elevation and returns the session's transport",
      _tab.set_pane_source(_pane_b, SOURCE_REMOTE) is True
      and _pane_b.elevated is False and _pane_b._elevated_client is None
      and _pane_b.source == SOURCE_REMOTE and _pane_b.provider is _worker
      and _pane_b._switch_state() == SOURCE_REMOTE,
      f"provider={_pane_b.provider!r} elevated={_pane_b.elevated}")
check("§4 ...and the user the pane was elevated as is remembered for the NEXT dialogue (data)",
      _pane_b._elevation_user == "admin" and _pane_b.elevated_label() == "admin")

_tab.set_pane_source(_pane_b, SOURCE_ELEVATED)
_client_b = FakeSftpClient(_fs)
_pane_b._handshake.ready.emit(_client_b, "/root")
check("§4 ...and the elevation can be taken again (the source control is a live choice)",
      _pane_b.elevated is True and _pane_b.source == SOURCE_REMOTE
      and _pane_b._elevation_user == "admin",
      f"elevated={_pane_b.elevated}")

_pane_b.transport_lost()
check("§4 a LOST transport drops the elevation with ONE sentence (never a dead listing)",
      _pane_b.elevated is False and _pane_b._elevated_client is None
      and _switch_msgs[-1:] == [i18n.t("sftp.elevated.lost", user="admin")],
      str(_switch_msgs[-2:]))

_tab.set_transport(FakeTransport())
_tab.set_pane_source(_pane_b, SOURCE_ELEVATED)
_client_c = FakeSftpClient(_fs)
_pane_b._handshake.ready.emit(_client_c, "/root")
_provider = _pane_b._elevated_provider
_tab.set_worker(_worker)
check("§4 the container's OWN rebinding never lands on an elevated pane (ONE provider per pane)",
      _provider is not None and _pane_b._bound_provider is _provider
      and _pane_b.provider is _provider and _pane_b.elevated is True,
      f"bound={_pane_b._bound_provider!r} provider={_pane_b.provider!r}")

_pane_b.release()
check("§4 release() stops the elevated provider and closes its client (the ONE teardown door)",
      _pane_b.elevated is False and _pane_b._elevated_client is None
      and getattr(_client_c, "_closed", False) is True
      and _pane_b._handshake is None,
      f"closed={getattr(_client_c, '_closed', None)} handshake={_pane_b._handshake}")
_pane_b.release()
check("§4 ...and the teardown is IDEMPOTENT (a second call is a quiet no-op)",
      _pane_b.elevated is False and _pane_b._elevated_provider is None)

_release_tab, _release_worker, _ = make_tab()
_release_tab.set_transport(FakeTransport())
_release_tab.set_pane_source(_release_tab.panes[1], SOURCE_ELEVATED)
_release_pane = _release_tab.panes[1]
_release_client = FakeSftpClient(_fs)
_release_pane._handshake.ready.emit(_release_client, "/root")
_release_hs = _release_pane._handshake
_release_tab.release()
check("§4 the CONTAINER's release takes the elevation of every pane too (the page's shutdown)",
      _release_pane.elevated is False and _release_pane._elevated_client is None
      and getattr(_release_client, "_closed", False) is True)

# ── The ask's TWO answers: a cancel is `None`, while the empty pair IS `root` (v1.8 review) ──

_root_tab, _root_worker, _ = make_tab()
_root_pane = _root_tab.panes[1]
_root_msgs = []
_root_pane.message.connect(_root_msgs.append)
_root_tab.set_transport(FakeTransport())
STAB.ask_elevation = lambda parent, current: ("", "")
check("§4 the EMPTY pair is NOT a cancel: it is `root` with no password and the handshake runs",
      _root_tab.set_pane_source(_root_pane, SOURCE_ELEVATED) is True
      and _root_pane._elevation_pending is True
      and isinstance(_root_pane._handshake, FakeHandshake)
      and _root_pane._handshake.user == "" and _root_pane._handshake.password == ""
      and _root_pane.elevated_label() == "root",
      f"handshake={_root_pane._handshake!r}")

# ── A late answer: the teardown drops the POSTED call, and the slot closes what still arrives ──

_late_tab, _late_worker, _ = make_tab()
_late_pane = _late_tab.panes[1]
_late_msgs = []
_late_pane.message.connect(_late_msgs.append)
_late_tab.set_transport(FakeTransport())
STAB.ask_elevation = _ask
_late_tab.set_pane_source(_late_pane, SOURCE_ELEVATED)
_late_handshake = _late_pane._handshake
_late_client = FakeSftpClient(_fs)
# The emission is QUEUED on purpose: a posted Qt call survives a `disconnect()` and lands later,
# which is exactly the delivery the teardown has to survive (`AGENTS.md` §4.3).
_late_handshake.ready.disconnect(_late_pane._on_elevation_ready)
_late_handshake.ready.connect(_late_pane._on_elevation_ready, Qt.ConnectionType.QueuedConnection)
_late_handshake.ready.emit(_late_client, "/root")
_late_seen = len(_late_msgs)
_late_tab.set_pane_source(_late_pane, SOURCE_REMOTE)
app.processEvents()   # the late call would be delivered here
check("§4 an answer that crosses the teardown is NEVER delivered (the posted call goes with the "
      "handshake)",
      _late_pane.elevated is False and _late_pane._elevated_provider is None
      and _late_pane.provider is _late_worker and len(_late_msgs) == _late_seen,
      f"elevated={_late_pane.elevated} provider={type(_late_pane.provider).__name__}")

_guard_tab, _guard_worker, _ = make_tab()
_guard_pane = _guard_tab.panes[1]
_guard_client = FakeSftpClient(_fs)
_guard_pane._on_elevation_ready(_guard_client, "/root")
check("§4 ...and an answer that still REACHES the slot elevates nothing and closes its client",
      _guard_pane.elevated is False and _guard_pane._elevated_provider is None
      and _guard_pane._elevated_client is None
      and getattr(_guard_client, "_closed", False) is True
      and _guard_pane.provider is _guard_worker,
      f"closed={getattr(_guard_client, '_closed', None)} provider={_guard_pane.provider!r}")


# ════════════════════════════════════════════════════════════
print("== §6 the contract, the documents and the release (ELEVATED_PANE.md §8) ==")
# ════════════════════════════════════════════════════════════

_contract = os.path.join(ROOT, "ELEVATED_PANE.md")
check("§8 the frozen contract of the version is in the tree", os.path.isfile(_contract), _contract)
_contract_text = open(_contract, encoding="utf-8").read() if os.path.isfile(_contract) else ""
check("§8 ...and it declares the read-only surface, the third provider and the ONE refusal",
      "READ-ONLY" in _contract_text and "THIRD provider" in _contract_text
      and "sftp.elevated.read_only" in _contract_text
      and "ELEVATED_PANE.md" in _contract_text)

_src = open(os.path.join(ROOT, "modules", "sftp_pane_elevated.py"), encoding="utf-8").read()
check("§5 the refusal is ONE sentence emitted from ONE place (no second wording of it)",
      _src.count('_t("sftp.elevated.read_only")') == 3
      and "_refuse_elevated_write" in _src and "_elevated_batch_refused" in _src
      and "sftp.elevated.read_only" not in
      open(os.path.join(ROOT, "modules", "sftp_pane_transfer.py"), encoding="utf-8").read())

_dialog_src = open(os.path.join(ROOT, "dialogs", "elevated_dialog.py"), encoding="utf-8").read()
check("§4 the dialogue validates the user with the PURE allowlist before a channel is opened",
      "user_problem(" in _dialog_src and "EchoMode.Password" in _dialog_src)

check("§6 every new sentence is present in all four language files (the parity gate)",
      len(_ELEVATED_KEYS) >= 15
      and all(str(_LANGS[code].get(k) or "").strip() for code in _LANGS for k in _ELEVATED_KEYS),
      str(_ELEVATED_KEYS))

_elev_src = open(os.path.join(ROOT, "modules", "sftp_elevated.py"), encoding="utf-8").read()
_log_lines = [ln for ln in _elev_src.splitlines() if ln.strip().startswith("log.")]
check("§6 no log line of the elevated provider can carry a secret (the password has no home)",
      not any("password" in ln.lower() for ln in _log_lines)
      and "self._password = \"\"" in _elev_src
      and "sendall" in _elev_src,
      str(_log_lines))
check("§6 ...and the password is never part of a command line (argv)",
      "self._password" not in _elev_src.split("sudo_prime_command")[0].split("def elevated_server_command")[-1]
      and "elevated_server_command(self._user" in _elev_src)

check_release_state(ROOT)
check_i18n_parity(_LANGS)
check_i18n_format(_LANGS)
check(f"the i18n pin of the release is the file's key count ({EXPECTED_I18N_KEYS})",
      all(len([k for k in data if k != "name"]) == EXPECTED_I18N_KEYS
          for data in _LANGS.values()),
      str({c: len([k for k in d if k != "name"]) for c, d in _LANGS.items()}))

# ── The teardown of the harness itself: no worker outlives the file ──
for _t in (_tab, _single_tab, _cancel_tab, _bad_tab, _fail_tab, _release_tab, _root_tab,
           _late_tab, _guard_tab):
    try:
        _t.release()
        _t.set_worker(None)
        _t.set_transport(None)
    except Exception:  # noqa: BLE001 — the harness teardown never fails the run
        pass
for _w in (_worker, _single_worker, _cancel_worker, _bad_worker, _fail_worker, _release_worker,
           _root_worker, _late_worker, _guard_worker):
    try:
        _w.shutdown()
    except Exception:  # noqa: BLE001 — the harness teardown never fails the run
        pass

finish()
