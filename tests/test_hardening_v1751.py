# -*- coding: utf-8 -*-
"""The v1.7.5.1 hardening patch: the nine LOCAL security defects of the shipped ledger.
tags: slow

Offscreen, no network. One section per ledger entry, each check reproducing the PROBE of the entry
against the shipped code: the external terminal's foreign command line (N41), the quick-launch
scheme (N42), the terminal's send path (N43), bracketed paste (N44), the download destination (N40),
the terminal's key branch (N50 minimum), the known_hosts store (N48), the provisional name (N53)
and the local walk (N55).
Contract — `AGENTS.md` §4.3/§4.4, `DOCUMENTATION.md` §14f/§16.

Run: python tests/test_hardening_v1751.py   (from the project root) or python tests/run_all.py"""

import io
import os
import posixpath
import socket
import stat
import subprocess
import sys
import threading
import time

from _common import (bootstrap, check, finish, wait_until, load_i18n_langs, check_i18n_parity,
                     check_release_state, EXPECTED_APP_VERSION, releases_at_least)

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QMimeData, QUrl

app = QApplication(sys.argv)

import i18n  # noqa: F401
import models.server as MS
import modules.external_terminal as ET
import modules.host_key_policy as HKP
import modules.local_fs_worker as LFW
import modules.sftp_send as SEND
import modules.sftp_worker as SW
import modules.terminal_widget as TW
from modules.terminal_screen import TerminalScreen

from _fakes import FakeSftpFS, FakeSftpClient, EventLog, wire_worker

print("== release pins ==")
check_release_state(ROOT)
check("the release this file describes is v1.7.5.1",
      releases_at_least(EXPECTED_APP_VERSION, "1.7.5.1"), EXPECTED_APP_VERSION)

# ════════════════════════════════════════════════════════════
# 1. N41 — the external terminal: the foreign command line (Windows)
# ════════════════════════════════════════════════════════════
print("== 1. N41: the external terminal ==")

check("N41 a space-free `&` host is REFUSED (it would be cmd syntax)",
      ET.host_problem("10.0.0.5&calc") == "characters"
      and ET.validate_target("10.0.0.5&calc", "root") == ET.TARGET_BAD_HOST)
check("N41 `%VAR%` and a UNC path are refused too",
      ET.host_problem("10.0.0.5&echo.%USERNAME%>x") == "characters"
      and ET.host_problem(r"\\attacker\share\x.exe") == "characters")
check("N41 a host that would become an ssh OPTION is refused",
      ET.host_problem("-oProxyCommand=calc") == "option")
check("N41 ordinary names survive: IPv4, a name, an IPv6 literal, a colon port",
      all(ET.host_problem(h) is None
          for h in ("10.0.0.5", "srv-01.example.com", "[fe80::1]", "host:2222")))
check("N41 a user with a metacharacter is refused, an ordinary one is not",
      ET.user_problem('ro"ot') == "characters" and ET.user_problem("root") is None
      and ET.user_problem("deploy.user-1_2") is None and ET.user_problem("") is None)
check("N41 the JUMP argument is judged by the same two rules",
      ET.jump_problem("ops@10.0.0.9") is None
      and ET.jump_problem("ops@10.0.0.9;calc") == "characters"
      and ET.validate_target("h", "u", "j@h;calc") == ET.TARGET_BAD_JUMP)
check("N41 `connect_external()` refuses BEFORE any launcher is looked for",
      ET.connect_external("10.0.0.5&calc", "root") == (False, ET.TARGET_BAD_HOST))
check("N41 `--` closes the option list before the address",
      ET.build_ssh_args("h1", "root") == ["ssh", "-o", "ConnectTimeout=10", "--", "root@h1"]
      and ET.build_ssh_args("-oProxyCommand=calc", "")[-2:] == ["--", "-oProxyCommand=calc"])
_cmd = ET.build_command("cmd", "10.0.0.5", "root")
check("N41 the cmd branch runs ssh DIRECTLY (no cmd.exe, no `start`, no parser to fool)",
      "cmd.exe" not in _cmd and "start" not in _cmd
      and _cmd[1:] == ET.build_ssh_args("10.0.0.5", "root")[1:], str(_cmd))
check("N41 a LEGAL key path with an `&` survives the cmd branch untouched",
      r"C:\Keys\R&D\id" in ET.build_command("cmd", "h", "u", 22, r"C:\Keys\R&D\id"))
check("N41 the POSIX branches are NOT ruled by the allowlist (they escape instead)",
      ET.build_command("konsole", "10.0.0.5", 'ro"ot')[-1].startswith("'ssh'")
      or "ssh" in ET.build_command("konsole", "10.0.0.5", 'ro"ot')[-1],
      ET.build_command("konsole", "10.0.0.5", 'ro"ot')[-1])
check("N41 the new refusal sentences exist in every language",
      all(str(load_i18n_langs(ROOT)[code].get(key) or "").strip()
          for code in ("en", "ru", "zh", "de")
          for key in ("ssh_ext.bad_host", "ssh_ext.bad_user", "ssh_ext.bad_jump")))

# The UI door: the shipped method, driven on a stub whose `__module__` is the facade's own, so the
# `host_attr()` seam resolves `_ext_term` exactly as it does in the window (AGENTS.md §4.1).
import ui.main_window as MW
import ui.main_window_ssh as MWS
from ui.main_window_ssh import SshMixin as _SshMixin

_ExtStub = type("_ExtStub", (), {"__module__": "ui.main_window"})


class _ExtNode:
    class data:
        host = "10.0.0.5&calc"
        user = "root"
        ssh_port = 22
        key_path = ""
        alias = "Hostile"


_ext = _ExtStub()
_ext.log = None
_ext._refuse_unmanaged = lambda node, key: False
_ext.t = lambda key, **kw: i18n.t(key, **kw) if kw else i18n.t(key)
_ext.statusBar = lambda: _Bar()
_orig_ext = MW._ext_term
_ext_boxes = []
MW._ext_term = ET
MWS.QMessageBox.warning = staticmethod(
    lambda *a, **k: _ext_boxes.append(a[2] if len(a) > 2 else ""))
try:
    _SshMixin._connect_ssh_external(_ext, _ExtNode())
finally:
    MW._ext_term = _orig_ext
check("N41 the WINDOW reports the refusal with its own sentence (never a silent return)",
      _ext_boxes == [i18n.t("ssh_ext.bad_host")], str(_ext_boxes))

# ════════════════════════════════════════════════════════════
# 2. N42 — the quick-launch scheme (Windows: webbrowser IS os.startfile)
# ════════════════════════════════════════════════════════════
print("== 2. N42: the opener's scheme allowlist ==")

check("N42 http/https are launchable, in any case",
      MS.is_launchable_url("https://wiki.example.com") and MS.is_launchable_url("HTTP://x/y"))
check("N42 a local path, a UNC path and a drive path are NOT",
      not MS.is_launchable_url(r"C:\Users\Public\x.exe")
      and not MS.is_launchable_url(r"\\attacker\share\x.exe")
      and not MS.is_launchable_url(r"F:\PythonAI\_ql_probe.cmd"))
check("N42 a foreign protocol handler is NOT (`ms-msdt:`, `file:`, `javascript:`)",
      not MS.is_launchable_url("ms-msdt:/id PCWDiagnostic")
      and not MS.is_launchable_url("file:///F:/x.exe")
      and not MS.is_launchable_url("javascript:alert(1)"))
check("N42 an empty value and a bare word are NOT",
      not MS.is_launchable_url("") and not MS.is_launchable_url("wiki.example.com"))
check("N42 the LOADER keeps the value (a URL is the user's data, never silently dropped)",
      [e["value"] for e in MS.sanitize_quick_launch(
          [{"type": "url", "name": "N", "value": r"\\attacker\share\x.exe"}])]
      == [r"\\attacker\share\x.exe"])
check("N42 the scheme reader uses urlsplit, never startswith (httpfoo:// is not http)",
      MS.url_scheme("httpfoo://x") == "httpfoo"
      and not MS.is_launchable_url("httpfoo://x"))

# The OPENER: the shipped method, driven on a stub `self` (the probe's technique).
_opened = []
_real_open = None
try:
    import webbrowser
    _real_open = webbrowser.open
    webbrowser.open = lambda url, *a, **k: (_opened.append(url), True)[1]
    _warned = []

    class _Bar:
        def showMessage(self, *a, **k):
            pass

    class _Stub:
        log = None

        def t(self, key, **kw):
            return key

        def statusBar(self):
            return _Bar()

    from ui.main_window_ssh import SshMixin
    import ui.main_window_ssh as MWS
    MWS.QMessageBox.warning = staticmethod(
        lambda *a, **k: _warned.append(a[2] if len(a) > 2 else ""))
    SshMixin._quick_launch_url(_Stub(), r"F:\PythonAI\_payload.cmd", "Innocent link")
    check("N42 the SHIPPED opener never reaches webbrowser.open for a refused value",
          _opened == [] and _warned == ["validation.ql_url_scheme"])
    SshMixin._quick_launch_url(_Stub(), "https://ok.example.com", "Docs")
    check("N42 ...while an http(s) link still opens",
          _opened == ["https://ok.example.com"] and len(_warned) == 1)
finally:
    if _real_open is not None:
        webbrowser.open = _real_open

# The three WRITERS share the ONE predicate.
import dialogs.bulk_edit_dialog as BED
from models.server import ServerData
_bulk = BED.BulkEditDialog()
_bulk.set_state(BED.FIELD_QUICK_LAUNCH, BED.STATE_SET)
_bulk.ql_name_edit.setText("Support")
_bulk.ql_value_edit.setText("ms-msdt:/id PCWDiagnostic")
check("N42 the bulk-edit writer refuses a bad scheme before accept()",
      _bulk.url_scheme_refused() is True and _bulk.state_of(BED.FIELD_QUICK_LAUNCH) == BED.STATE_SET)
check("N42 ...and accept() blocks on it (the dialog never closes)",
      _bulk.accept() is None and _bulk.result() != 1, str(_bulk.result()))
_bulk.ql_value_edit.setText("https://ok.example.com")
check("N42 ...and accepts an http(s) one", _bulk.url_scheme_refused() is False)
_bulk.ql_type_combo.setCurrentIndex(1)   # "command"
_bulk.ql_value_edit.setText("systemctl restart nginx")
check("N42 a `command` entry is not judged by the URL rule",
      _bulk.url_scheme_refused() is False)
_bulk.deleteLater()

import inspect
import dialogs.quick_launch_dialog as QLD
import dialogs.bookmark_edit_dialog as BMD
check("N42 the quick-launch editor asks the ONE predicate (no second wording of the rule)",
      "is_launchable_url" in inspect.getsource(QLD.QuickLaunchDialog._add_entry)
      and "startswith" not in inspect.getsource(QLD.QuickLaunchDialog._add_entry))
check("N42 the bookmark editor asks it too",
      "is_launchable_url" in inspect.getsource(BMD.BookmarkEditDialog._apply_fields))

# ════════════════════════════════════════════════════════════
# 3. N43 — the send path: no truncation, no fatal timeout
# ════════════════════════════════════════════════════════════
print("== 3. N43: the terminal's send path ==")


class _Sink:
    """The transport's message sink — the ONLY fake part of the paramiko half."""

    def __init__(self):
        self.payloads = []

    def _send_user_message(self, message):
        self.payloads.append(message)


def real_channel(chanid):
    import paramiko
    ch = paramiko.Channel(chanid)
    ch.remote_chanid = 100 + chanid
    ch.out_window_size = 2 * 1024 * 1024
    ch.out_max_packet_size = 32768
    ch.transport = _Sink()
    return ch


def delivered(ch):
    total = 0
    for message in ch.transport.payloads:
        message.rewind()
        message.get_byte()
        message.get_int()
        total += len(message.get_binary())
    return total


DATA40K = b"A" * 40000
_ch = real_channel(0)
_ch.send(DATA40K)
check("N43 ONE `channel.send()` really truncates at ~32 KB (the defect, reproduced)",
      delivered(_ch) == 32704 and delivered(_ch) < len(DATA40K), str(delivered(_ch)))

import modules.ssh_terminal as ST

_thread = ST.SSHTerminalThread("h", "u", 22)
_ch2 = real_channel(1)
_thread.channel = _ch2
_errors = []
_thread.error_signal.connect(_errors.append)
_thread.send_data(DATA40K)
check("N43 the SHIPPED `send_data()` delivers ALL 40000 bytes (the loop on the byte count)",
      delivered(_ch2) == len(DATA40K) and _errors == [],
      f"delivered={delivered(_ch2)} errors={_errors}")


class _Stalled:
    """A channel whose send window never opens — paramiko raises a MESSAGE-LESS socket.timeout."""

    closed = False

    def __init__(self):
        self.calls = 0

    def send(self, data):
        self.calls += 1
        raise socket.timeout()


_stalled = _Stalled()
_thread2 = ST.SSHTerminalThread("h", "u", 22)
_thread2.channel = _stalled
_errors2 = []
_statuses = []
_thread2.error_signal.connect(_errors2.append)
_thread2.status_signal.connect(_statuses.append)
_thread2.send_data(b"X" * 100)
check("N43 a stalled window emits NO error_signal (no modal, no closed session)",
      _errors2 == [], str(_errors2))
check("N43 ...and the bytes are PARKED for the session thread, in order",
      bytes(_thread2._pending) == b"X" * 100, repr(bytes(_thread2._pending))[:40])
check("N43 `send_data()` never calls `sendall` with a message-less timeout escaping",
      str(socket.timeout()) == "" and _stalled.calls >= 1)


class _Windowed:
    """A channel that refuses until the window opens, then accepts everything."""

    closed = False

    def __init__(self):
        self.buffer = bytearray()
        self.open = False

    def send(self, data):
        if not self.open:
            raise socket.timeout()
        chunk = bytes(data)[:32704]
        self.buffer.extend(chunk)
        return len(chunk)


_windowed = _Windowed()
_thread4 = ST.SSHTerminalThread("h", "u", 22)
_thread4.channel = _windowed
_thread4.send_data(b"Y" * 40000)
check("N43 (setup) nothing crossed while the window was shut", _windowed.buffer == bytearray())
_windowed.open = True
check("N43 the session thread's drain flushes the parked bytes", _thread4._flush_pending() is True)
check("N43 ...and the drain LOOPS until the buffer is empty (all 40000)",
      bytes(_windowed.buffer) == b"Y" * 40000 and not _thread4._pending,
      f"{len(_windowed.buffer)} / pending={len(_thread4._pending)}")

_thread5 = ST.SSHTerminalThread("h", "u", 22)
_thread5.channel = _Stalled()
_statuses5 = []
_thread5.status_signal.connect(_statuses5.append)
_thread5._pending.extend(b"Z" * (ST.MAX_SEND_QUEUE_BYTES + 1024))
_thread5.send_data(b"Q" * 10)
check("N43 the parked queue is BOUNDED",
      len(_thread5._pending) == ST.MAX_SEND_QUEUE_BYTES, str(len(_thread5._pending)))
check("N43 ...and the overflow is said ONCE on the STATUS line (never through error_signal)",
      len(_statuses5) == 1 and str(_statuses5[0]) == i18n.t("terminal.send_queue_full")
      and _errors2 == [], str(_statuses5))


class _SlowWindow:
    """A channel whose send window opens a little at a time — the slow remote container.

    `send_ready()` answers paramiko's own question; a sender that ASKS it writes what fits and parks
    the rest, while a sender that WAITS pays the channel timeout (0.2 s) for every ~32 KB packet.
    """

    closed = False

    def __init__(self, window=1024):
        self.window = window
        self.buffer = bytearray()
        self.waits = 0

    def send_ready(self):
        return self.window > 0

    def send(self, data):
        if self.window <= 0:
            self.waits += 1      # the BLOCKING path the GUI thread must never take
            time.sleep(0.05)
            raise socket.timeout()
        chunk = bytes(data)[:self.window]
        self.buffer.extend(chunk)
        self.window -= len(chunk)
        return len(chunk)


_slow = _SlowWindow()
_thread6 = ST.SSHTerminalThread("h", "u", 22)
_thread6.channel = _slow
_t0 = time.time()
_thread6.send_data(b"W" * 100000)
_elapsed = time.time() - _t0
check("N43 the GUI thread ASKS the window (`send_ready()`) instead of waiting for it",
      "send_ready" in inspect.getsource(ST.SSHTerminalThread._window_open)
      and _slow.waits == 0 and _elapsed < 0.05, f"waits={_slow.waits} elapsed={_elapsed:.3f}s")
check("N43 ...and the refused remainder is PARKED for the session thread, in order",
      bytes(_slow.buffer) == b"W" * 1024
      and bytes(_thread6._pending) == b"W" * (100000 - 1024),
      f"sent={len(_slow.buffer)} parked={len(_thread6._pending)}")
_slow.window = 200000
check("N43 the drain writes what the window then allows WITHOUT holding the lock for a wait",
      _thread6._flush_pending() is True and not _thread6._pending and _slow.waits == 0,
      f"parked={len(_thread6._pending)} waits={_slow.waits}")

# ════════════════════════════════════════════════════════════
# 4. N44 — bracketed paste is CONDITIONAL
# ════════════════════════════════════════════════════════════
print("== 4. N44: bracketed paste ==")

_screen = TerminalScreen(20, 5)
check("N44 the mode is OFF before the application asks", _screen.bracketed_paste_enabled() is False)
_screen.feed(b"\x1b[?2004h")
check("N44 DECSET 2004 is READ from the shipped vendored pyte (no fork patch)",
      _screen.bracketed_paste_enabled() is True)
_screen.feed(b"\x1b[?2004l")
check("N44 DECRST 2004 turns it off again", _screen.bracketed_paste_enabled() is False)
check("N44 a password-like clipboard is RAW while the mode is off (the sudo/passwd case)",
      TW.build_macro_payload("hunter2!", bracketed_paste=False) == b"hunter2!\n")
check("N44 ...and WRAPPED while it is on (bash >= 5.1 asks for it)",
      TW.build_macro_payload("a\nb", bracketed_paste=True) == b"\x1b[200~a\nb\n\x1b[201~")
check("N44 a multi-line macro without the mode arrives as plain lines",
      TW.build_macro_payload("a\nb", bracketed_paste=False) == b"a\nb\n")
check("N44 the additive default keeps the shipped bytes for a caller with no screen",
      TW.build_macro_payload("a\nb") == b"\x1b[200~a\nb\n\x1b[201~")
check("N44 a clipboard carrying the END marker cannot close the paste early",
      TW.strip_paste_markers("echo SAFE\x1b[201~echo PWNED\n") == "echo SAFEecho PWNED\n"
      and TW.strip_paste_markers("a\x1b[200~b") == "ab")
check("N44 the widget asks the SCREEN, not the config",
      "_paste_mode_enabled" in inspect.getsource(TW.TerminalWidget._bracketed_paste)
      and "bracketed_paste_enabled" in inspect.getsource(TW.TerminalWidget._paste_mode_enabled))

# ════════════════════════════════════════════════════════════
# 5. N40 — a server NAME must not become a local PATH
# ════════════════════════════════════════════════════════════
print("== 5. N40: the download destination ==")

check("N40 a `..\\` chain is refused on Windows and LEGAL on POSIX",
      SW.local_name_problem(r"..\escape.txt") == "characters"
      and SW.local_name_problem(r"..\escape.txt", windows=False) is None)
check("N40 a colon (an NTFS alternate data stream) is refused on Windows only",
      SW.local_name_problem("backup_12:00.tar") == "characters"
      and SW.local_name_problem("backup_12:00.tar", windows=False) is None)
check("N40 the reserved DEVICE names are refused, with and without an extension, any case",
      all(SW.local_name_problem(n) == "reserved"
          for n in ("NUL", "nul.txt", "CON", "com1", "LPT9.log")))
check("N40 a trailing dot or space is refused (two distinct names collapse into one)",
      SW.local_name_problem("trailing.") == "trailing"
      and SW.local_name_problem("trailing ") == "trailing"
      and SW.local_name_problem("notes. ", windows=False) is None)
check("N40 `.`, `..` and an empty name are refused",
      SW.local_name_problem(".") == "relative"
      and SW.local_name_problem("..") == "relative"
      and SW.local_name_problem("") == "empty")
check("N40 a legal POSIX name on Windows is refused for the RIGHT reason (a separator)",
      SW.local_name_problem(r"a\b.txt") == "characters"
      and SW.local_name_problem(r"a\b.txt", windows=False) is None)
check("N40 a control character is refused",
      SW.local_name_problem("a\x01b") == "control")
check("N40 an ordinary name passes in BOTH modes",
      all(SW.local_name_problem(n, windows=w) is None
          for n in ("report.txt", "archive.tar.gz", "файл.log")
          for w in (True, False)))
check("N40 the CONTAINMENT BELT sees what `startswith()` cannot",
      SW.local_containment_problem(os.path.join(WORK, "..", "escape.txt"), WORK) == "outside"
      and os.path.join(WORK, "..", "escape.txt").startswith(WORK))
check("N40 ...and a real child stays inside",
      SW.local_containment_problem(os.path.join(WORK, "sub", "a.txt"), WORK) is None)
check("N40 the provisional name of a transfer stays inside its own folder",
      SW.local_destination_problem("a.txt", WORK) is None)

# The WORKER: the last mile. A hostile row fails ALONE and its bytes land nowhere.
_fs = FakeSftpFS()
_fs.add_dir("/share")
_fs.add_file(r"/share/..\escape.txt".replace("\\", "\\"), b"payload")
_fs.files["/share/..\\escape.txt"] = b"payload"
_dl = os.path.join(WORK, "n40_dl")
os.makedirs(_dl, exist_ok=True)
_worker = SW.SftpWorker(FakeSftpClient(_fs))
_log = EventLog()
wire_worker(_worker, _log)
_worker.start()
_tid = _worker.queue_download("/share/..\\escape.txt", _dl)
wait_until(lambda: _log.of_kind("error", _tid), timeout_ms=5000)
_err = _log.of_kind("error", _tid)
_payload = SW.parse_task_payload(_err[0][3]) if _err else None
check("N40 the worker REFUSES the hostile name with the machine payload",
      _payload is not None and _payload.get("code") == SW.NAME_ERROR_UNSAFE, str(_err))
check("N40 nothing was written outside the chosen folder",
      sorted(os.listdir(_dl)) == [] and not os.path.exists(os.path.join(WORK, "escape.txt")),
      str(sorted(os.listdir(_dl))))
check("N40 ...and no provisional litter is left",
      [n for n in os.listdir(_dl) if n.endswith(SW.PART_SUFFIX)] == [])
check("N40 the payload names the file, so the pane can spell the sentence",
      _payload.get("name") == "..\\escape.txt", str(_payload))
_worker.shutdown(wait_ms=2000)

# A hostile name INSIDE a tree: the tree is ONE task, so its failure is the PARTIAL payload.
_fs_tree = FakeSftpFS()
_fs_tree.add_dir("/tree")
_fs_tree.add_file("/tree/ok.txt", b"ok")
_fs_tree.add_file("/tree/bad:name.csv", b"x")
_fs_tree.add_file("/tree/zzz.txt", b"z")
_tw = SW.SftpWorker(FakeSftpClient(_fs_tree))
_tlog = EventLog()
wire_worker(_tw, _tlog)
_tw.start()
_ttid = _tw.queue_download("/tree", os.path.join(WORK, "n40_tree"))
wait_until(lambda: _tlog.of_kind("error", _ttid), timeout_ms=8000)
_terr = _tlog.of_kind("error", _ttid)
_tpayload = SW.parse_task_payload(_terr[0][3]) if _terr else None
check("N40 one refused name in a TREE stops it as the TREE's PARTIAL, not as a bare refusal",
      _tpayload is not None and _tpayload.get("code") == SW.PARTIAL_CODE, str(_terr))
check("N40 ...and that payload CARRIES the refusal (its own machine code and reason)",
      isinstance(_tpayload, dict)
      and (SW.parse_task_payload(str(_tpayload.get("error") or ""), SW.NAME_ERROR_UNSAFE)
           or {}).get("name") == "bad:name.csv", str(_tpayload))
check("N40 the tree's log line says how far it got AND names the refused file (no JSON)",
      "partially done" in SW.task_log_line("download", "tree", SW.OUTCOME_FAILED,
                                            str(_terr[0][3]))[0]
      and "bad:name.csv" in SW.task_log_line("download", "tree", SW.OUTCOME_FAILED,
                                             str(_terr[0][3]))[0],
      SW.task_log_line("download", "tree", SW.OUTCOME_FAILED, str(_terr[0][3]))[0])
_tw.shutdown(wait_ms=2000)

import modules.sftp_tab as STAB
check("N40 the pane renders that payload as ONE translated sentence",
      STAB.name_refusal_text(SW.task_payload(SW.NAME_ERROR_UNSAFE, name="nul.txt"))
      not in ("", "sftp.name_refused")
      and "nul.txt" in STAB.name_refusal_text(
          SW.task_payload(SW.NAME_ERROR_UNSAFE, name="nul.txt")))
check("N40 the GUI pre-check asks the same predicate (and only for a remote source)",
      "local_name_problem" in inspect.getsource(STAB._SftpPane._queue_downloads))
check("N40 the new sentence exists in all four languages",
      all("sftp.name_refused" in load_i18n_langs(ROOT)[code]
          for code in ("en", "ru", "zh", "de")))

# ════════════════════════════════════════════════════════════
# 6. N50 (minimum) — the terminal's key branch passes the password; (1.8rc6) the ONE builder
# ════════════════════════════════════════════════════════════
print("== 6. N50: the terminal's key branch ==")

import modules.ssh_connect as SCON

_kw_key = SCON.build_connect_kwargs("h", "u", 22, password="pw", key_path="/k/id")
_kw_key_pure = SCON.build_connect_kwargs("h", "u", 22, key_path="/k/id")
_kw_pw = SCON.build_connect_kwargs("h", "u", 22, password="pw")
_kw_agent = SCON.build_connect_kwargs("h", "u", 22)
check("N50 the KEY branch passes `password=self.password or None` and the shipped key pair",
      _kw_key.get("password") == "pw" and _kw_key.get("key_filename") == "/k/id"
      and _kw_key.get("look_for_keys") is False and _kw_key.get("allow_agent") is True,
      str(_kw_key))
check("N50 ...a key with NO password passes an explicit None (paramiko skips it)",
      _kw_key_pure.get("password") is None
      and _kw_key_pure.get("key_filename") == "/k/id", str(_kw_key_pure))
check("N50/pw the password branch polls neither the local keys nor the agent",
      _kw_pw.get("password") == "pw" and _kw_pw.get("look_for_keys") is False
      and _kw_pw.get("allow_agent") is False, str(_kw_pw))
check("N50/agent the shipped fallback is the key/agent pair",
      _kw_agent.get("look_for_keys") is True and _kw_agent.get("allow_agent") is True
      and "key_filename" not in _kw_agent, str(_kw_agent))
check("N50 the four connect sites now share the ONE builder (no copy left)",
      all(open(os.path.join(ROOT, p), encoding="utf-8").read().count("connect_client(") == 1
          for p in ("modules/ssh_terminal.py", "modules/ssh_worker.py",
                    "modules/plugin_runner.py", "services/system_info_collector.py"))
      and "client.connect(" not in open(os.path.join(ROOT, "modules", "ssh_terminal.py"),
                                        encoding="utf-8").read())

# ════════════════════════════════════════════════════════════
# 7. N48 — the known_hosts store: ONE owner, merge-on-write, atomic, visible
# ════════════════════════════════════════════════════════════
print("== 7. N48: the known_hosts store ==")

import paramiko
from paramiko.hostkeys import HostKeys

TEMP = os.path.join(WORK, "n48_known_hosts")
_original_store = HKP.get_store()
HKP.set_store(HKP.KnownHostsStore(path=TEMP))


def key_for(tag):
    return paramiko.ECDSAKey.generate()


class _Client:
    def __init__(self):
        self._keys = HostKeys()

    def set_missing_host_key_policy(self, policy):
        self.policy = policy

    def get_host_keys(self):
        return self._keys


def pin(host):
    policy = HKP.SshKnownHostsPolicy(host, 22)
    policy.apply_to_client(_Client())
    policy.missing_host_key(None, host, key_for(host))
    return policy


def hosts_in_file():
    store = HostKeys()
    try:
        store.load(TEMP)
    except Exception:
        return ["<unreadable>"]
    return sorted(store.keys())


try:
    if os.path.exists(TEMP):
        os.remove(TEMP)
    # §B of the probe: a LONG-LIVED session must not wipe a key pinned meanwhile.
    _first = HKP.SshKnownHostsPolicy("host-a", 22)
    _first.apply_to_client(_Client())
    pin("host-b")
    _first.missing_host_key(None, "host-a", key_for("a"))
    check("N48 a long-lived session does NOT wipe a key pinned meanwhile (merge-on-write)",
          hosts_in_file() == ["host-a", "host-b"], str(hosts_in_file()))
    check("N48 the policy reports that the key really reached the store",
          _first.pinned is True and _first.accepted_new_key is True)

    # §C of the probe: eight concurrent connections keep eight entries.
    if os.path.exists(TEMP):
        os.remove(TEMP)
    HKP.set_store(HKP.KnownHostsStore(path=TEMP))
    _barrier = threading.Barrier(8)
    _errors = []

    def _worker(n):
        try:
            _barrier.wait(timeout=5)
            pin("host-%d" % n)
        except Exception as exc:  # noqa: BLE001
            _errors.append(repr(exc))

    _threads = [threading.Thread(target=_worker, args=(n,)) for n in range(8)]
    for th in _threads:
        th.start()
    for th in _threads:
        th.join()
    check("N48 eight CONCURRENT pins keep all eight entries (1 of 8 before the fix)",
          len(hosts_in_file()) == 8, f"kept={hosts_in_file()} errors={_errors[:1]}")

    # §A: the write is atomic — no `.tmp` survives, and the published file is whole.
    check("N48 the atomic publish leaves no `.tmp` behind",
          not os.path.exists(TEMP + ".tmp") and len(hosts_in_file()) == 8)

    # §D: an UNREADABLE store accepts (TOFU) but does NOT claim to pin, and says so.
    with open(TEMP, "w", encoding="utf-8") as fh:
        fh.write("this is not a known_hosts file\n<<< truncated\n")
    HKP.set_store(HKP.KnownHostsStore(path=TEMP))
    _victim = HKP.SshKnownHostsPolicy("any-host", 22)
    _victim.apply_to_client(_Client())
    try:
        _victim.missing_host_key(None, "any-host", key_for("any"))
        _accepted = True
    except Exception:  # noqa: BLE001
        _accepted = False
    check("N48 an unreadable store still accepts the first contact (TOFU by design)", _accepted)
    check("N48 ...but `pinned` is False, so the session is reported as UNPINNED",
          _victim.pinned is False and _victim.load_failed is True)
    check("N48 ...and the corrupt file is left EXACTLY as it was (never overwritten)",
          open(TEMP, encoding="utf-8").read().startswith("this is not a known_hosts file"))
    check("N48 the PUBLIC `save()` seam makes the SAME refusal (one store, one rule)",
          _victim.store.save() is False
          and open(TEMP, encoding="utf-8").read().startswith("this is not a known_hosts file"),
          open(TEMP, encoding="utf-8").read()[:40])
    check("N48 ...while a READABLE store still saves through that same door",
          HKP.KnownHostsStore(path=os.path.join(WORK, "n48_readable")).save() is True)
    check("N48 the terminal and the worker report the unpinned state separately",
          "ssh.host_key_unpinned" in open(os.path.join(ROOT, "modules", "ssh_terminal.py"),
                                          encoding="utf-8").read()
          and "ssh.host_key_unpinned" in open(os.path.join(ROOT, "modules", "ssh_worker.py"),
                                              encoding="utf-8").read())
    check("N48 the warning sentence exists in all four languages",
          all("ssh.host_key_unpinned" in load_i18n_langs(ROOT)[code]
              for code in ("en", "ru", "zh", "de")))

    # §E: a healthy store still REJECTS a changed key.
    if os.path.exists(TEMP):
        os.remove(TEMP)
    HKP.set_store(HKP.KnownHostsStore(path=TEMP))
    pin("host-x")
    _other = key_for("other")
    try:
        HKP.SshKnownHostsPolicy("host-x", 22).check("host-x", _other)
        _rejected = False
    except paramiko.SSHException:
        _rejected = True
    check("N48 a CHANGED key for a pinned host is still rejected", _rejected)
    check("N48 the `check()` guard reads through the ONE store (no session snapshot)",
          "self.store.lookup" in inspect.getsource(HKP.SshKnownHostsPolicy.check))
finally:
    if os.path.exists(TEMP):
        os.remove(TEMP)
    HKP.set_store(_original_store)

# ════════════════════════════════════════════════════════════
# 8. N53 — the provisional name is the WRITER's
# ════════════════════════════════════════════════════════════
print("== 8. N53: the provisional name ==")

check("N53 the name keeps the `.part` suffix every reader knows",
      SW.provisional_name("/d/f.bin", 7).endswith(SW.PART_SUFFIX)
      and SW.provisional_name("/d/f.bin", 7) == "/d/f.bin.%d-7.part" % os.getpid())
check("N53 ...and gains the owner: two tasks on ONE target differ",
      SW.provisional_name("/d/f.bin", 1) != SW.provisional_name("/d/f.bin", 2))
check("N53 the token carries the PROCESS as well as the task",
      SW.provisional_name("/d/f.bin", 7) == f"/d/f.bin.{os.getpid()}-7.part",
      SW.provisional_name("/d/f.bin", 7))
check("N53 an explicit token wins (the seam a caller may pass)",
      SW.provisional_name("/d/f.bin", 7, token="X") == "/d/f.bin.X.part")
check("N53 the three transfer bodies all read the ONE helper",
      all("provisional_name(" in inspect.getsource(fn)
          for fn in (SW.SftpWorker._upload_file, SW.SftpWorker._download_file,
                     SW.SftpWorker._copy_file, LFW.LocalFsWorker._copy_file)))

# The FOREIGN provisional file survives a cancelled upload (it is not ours).
_fs2 = FakeSftpFS()
_fs2.add_dir("/dst")
_fs2.add_file("/dst/report.bin.part", b"ANOTHER TOOL'S HALF-WRIT")
_client2 = FakeSftpClient(_fs2)
_worker2 = SW.SftpWorker(_client2)
_log2 = EventLog()
wire_worker(_worker2, _log2)
_worker2.start()
_local2 = os.path.join(WORK, "n53_src.bin")
with open(_local2, "wb") as fh:
    fh.write(b"z" * 100)
_tid2 = _worker2.queue_upload(_local2, "/dst", remote_name="report.bin")
wait_until(lambda: _log2.of_kind("done", _tid2), timeout_ms=5000)
check("N53 a foreign `<target>.part` is untouched by OUR upload (a different token)",
      _fs2.files.get("/dst/report.bin.part") == b"ANOTHER TOOL'S HALF-WRIT",
      str(sorted(_fs2.files)))
check("N53 ...and the destination holds our bytes",
      _fs2.files.get("/dst/report.bin") == b"z" * 100)

# The MODE of a provisional file belongs to the WRITER: `os.replace()` publishes THAT inode.
_fs3 = FakeSftpFS()
_fs3.add_dir("/m")
_fs3.add_file("/m/secret.bin", b"secret bytes")
_w3 = SW.SftpWorker(FakeSftpClient(_fs3))
_log3 = EventLog()
wire_worker(_w3, _log3)
_w3.start()
_landed = os.path.join(WORK, "n53_mode.bin")
_mtid = _w3.queue_download("/m/secret.bin", WORK, local_name="n53_mode.bin",
                           part_mode=0o600)
wait_until(lambda: _log3.of_kind("done", _mtid), timeout_ms=5000)
check("N53 the download body CREATES its provisional file through the ONE mode-aware opener",
      "_open_partial(temp, task.part_mode)" in inspect.getsource(SW.SftpWorker._download_file)
      and "os.open(" in inspect.getsource(SW._open_partial))
check("N53 the committed file carries the mode the CALLER asked for (POSIX; Windows decides)",
      stat.S_IMODE(os.stat(_landed).st_mode) == 0o600 if os.name != "nt" else True,
      oct(os.stat(_landed).st_mode))
_w3.shutdown(wait_ms=2000)
check("N53 the relay asks the spool's tight mode from that ONE writer (not from a twin name)",
      "part_mode=SPOOL_FILE_MODE" in inspect.getsource(SEND.SendRelay.start)
      and SEND.SPOOL_FILE_MODE == 0o600)
check("N53 a cancelled upload leaves no provisional file of its own",
      [p for p in _fs2.files if p.endswith(SW.PART_SUFFIX)] == ["/dst/report.bin.part"],
      str(sorted(_fs2.files)))
_worker2.shutdown(wait_ms=2000)

# ════════════════════════════════════════════════════════════
# 9. N55 — the local walk: a JUNCTION and an unreadable folder
# ════════════════════════════════════════════════════════════
print("== 9. N55: the local walk ==")

_link_ok = False
_junction_root = os.path.join(WORK, "n55_junction")
_target = os.path.join(WORK, "n55_target")
os.makedirs(_junction_root, exist_ok=True)
os.makedirs(_target, exist_ok=True)
with open(os.path.join(_target, "inside.txt"), "wb") as fh:
    fh.write(b"secret")
with open(os.path.join(_junction_root, "plain.txt"), "wb") as fh:
    fh.write(b"plain")
_link = os.path.join(_junction_root, "junction")
if sys.platform == "win32":
    result = subprocess.run(["cmd", "/c", "mklink", "/J", _link, _target],
                            capture_output=True, text=True)
    _link_ok = result.returncode == 0 and os.path.isdir(_link)
else:
    try:
        os.symlink(_target, _link)
        _link_ok = True
    except OSError:
        _link_ok = False

if _link_ok:
    check("N55 a Windows JUNCTION is seen by `is_directory_link()` (os.path.islink does not)",
          SW.is_directory_link(_link) is True
          and (os.path.islink(_link) is False if sys.platform == "win32" else True),
          f"islink={os.path.islink(_link)}")
    _fs3 = FakeSftpFS()
    _worker3 = SW.SftpWorker(FakeSftpClient(_fs3))
    _entries = [p for p, _d, _s in _worker3._walk_local_tree(_junction_root)]
    check("N55 the upload walk does NOT leave the folder through the link",
          not any("inside.txt" in p for p in _entries), str(_entries))
    _engine = LFW.LocalFsWorker()
    _entries2 = [p for p, _d, _s in _engine._walk_tree(_junction_root)]
    check("N55 ...and neither does the local copy/move engine",
          not any("inside.txt" in p for p in _entries2), str(_entries2))
    try:
        LFW.LocalFsWorker._refuse_symlinked_dir(_link)
        _refused = False
    except Exception:  # noqa: BLE001
        _refused = True
    check("N55 the ROOT of a copy/move refuses the link as well", _refused)
    check("N55 a plain directory is not a link",
          SW.is_directory_link(_junction_root) is False
          and SW.is_directory_link(os.path.join(WORK, "no-such-path")) is False)
else:
    check("N55 (skipped) this environment cannot create a junction", True)

# The unreadable folder: `os.listdir` must not end the whole walk.
_denied = os.path.join(WORK, "n55_denied")
os.makedirs(_denied, exist_ok=True)
_real_listdir = os.listdir


def _fake_listdir(path):
    if os.path.abspath(str(path)) == os.path.abspath(_denied):
        raise PermissionError(13, "Permission denied")
    return _real_listdir(path)


os.listdir = _fake_listdir
try:
    _fs4 = FakeSftpFS()
    _worker4 = SW.SftpWorker(FakeSftpClient(_fs4))
    try:
        _w4 = [p for p, _d, _s in _worker4._walk_local_tree(WORK)]
        _raised = False
    except PermissionError:
        _w4, _raised = [], True
    _engine2 = LFW.LocalFsWorker()
    try:
        _w5 = [p for p, _d, _s in _engine2._walk_tree(WORK)]
        _raised5 = False
    except PermissionError:
        _w5, _raised5 = [], True
finally:
    os.listdir = _real_listdir

check("N55 ONE unreadable folder no longer aborts the upload walk (the folder is SKIPPED)",
      _raised is False, "PermissionError escaped _walk_local_tree")
check("N55 ...and the rest of the tree is still walked",
      any(p.endswith("plain.txt") for p in _w4), str(_w4[:4]))
check("N55 ...and the local engine's walk behaves the same way",
      _raised5 is False and any(p.endswith("plain.txt") for p in _w5))

check_i18n_parity(load_i18n_langs(ROOT))

finish()
