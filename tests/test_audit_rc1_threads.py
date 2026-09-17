# -*- coding: utf-8 -*-
"""v1.2.10rc1 — Audit: threads and teardown (AUDIT.md auto #2 + manual #1 + a verification finding).

The thematic test of the release (ROADMAP v1.2.10rc1; offscreen, the fake threads — without the network):

§1 The DNS guard (auto #2): two quick "Copy Hostname" → ONE ReverseDnsThread,
   the repeated request is ignored with the status message (without the clobbering of the running
   thread); the thread is created with parent=MainWindow; after finished() — the cleanup
   of self._dns_thread + the clipboard; the guard is released — the next request starts.

§2 closeEvent with a hanging fake DNS thread (the finding of the verification): the window is closed
   within the wait budget (~2 s, does not hang), the surviving thread — in the orphan registry
   services/diagnostics._orphan_threads (not left to the GC: "QThread: Destroyed
   while thread is still running"), the registry self-cleans on finished().

§3 The shutdown with 2 active terminal sessions at terminal_close_behavior="ask"
   (manual #1, the real bug): ZERO QMessageBox.question (the seam ST.QMessageBox.question
   is patched) — the "ask" gate is passed via _force_close (the path of the limit v1.1.1),
   the main window is closed; the surviving threads — in ST._orphan_threads (the N4 path).

§4 The release state + the i18n parity (427 — no NEW keys: the guard message
   reuses the existing status.import_resolving).

Run:  python tests/test_audit_rc1_threads.py   (from the project root) or python tests/run_all.py
"""
# tags: slow
# the reason: the ~2 s wait budgets in the teardown scenarios (§2, §3 — part of the specification)

import json
import os
import sys
import threading
import time

from _common import (bootstrap, check, finish, wait_until,
                     load_i18n_langs, check_i18n_parity, check_release_state)

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from PySide6.QtCore import QThread, Signal as QtSignal
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication(sys.argv)

import services.diagnostics as diag
import modules.ssh_terminal as ST
import ui.main_window as MW
from models.server import ServerData


# ════════════════════════════════════════════════════════════
# The harness: fake threads (the same API as the real ones)
# ════════════════════════════════════════════════════════════

class _HangingDnsThread(QThread):
    """The fake ReverseDnsThread: run() hangs until the release() (the unavailable resolver —
    the getaddrinfo lives out its timeout), the stop() method is ABSENT — exactly as in the real
    ReverseDnsThread/PingThread (the finding of the verification)."""

    resolved = QtSignal(str)

    def __init__(self, host_, parent=None):
        super().__init__(parent)
        self._host = host_
        self._release = threading.Event()

    def run(self):
        self._release.wait(30)   # "getaddrinfo" — stop() does not interrupt it (it has none)
        try:
            self.resolved.emit(self._host)
        except RuntimeError:
            pass  # the window is already destroyed — a late emit without receivers is safe

    def release(self):
        self._release.set()


class _BlockingTermThread(QThread):
    """The fake SSHTerminalThread: run() blocks until the release(); stop() only
    sets running=False and does NOT interrupt run() — as the paramiko connection
    with the timeout of 15 s (the scenario N4 v1.1.2RC1)."""

    output_signal = QtSignal(bytes)
    error_signal = QtSignal(str)
    status_signal = QtSignal(str)
    closed_signal = QtSignal()
    connected_signal = QtSignal()

    def __init__(self, host, user, port, password="", key_path=""):
        super().__init__()
        self.host, self.user, self.port = host, user, port
        self.password, self.key_path = password, key_path
        self.client = None
        self.channel = None
        self.running = True
        self.stop_calls = 0
        self._release = threading.Event()

    def run(self):
        self._release.wait(30)   # "connection" — stop() does not interrupt it
        self.running = False
        try:
            self.closed_signal.emit()
        except RuntimeError:
            pass  # the page is already destroyed — a late emit without receivers is safe

    def stop(self):
        self.stop_calls += 1
        self.running = False     # does NOT interrupt run() (the recv loop exits by itself in ~30 ms)

    def release(self):
        self._release.set()


def _cfg_path():
    return os.path.join(os.path.expanduser("~"), ".sshmap", "config.json")


def write_config(d):
    p = _cfg_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f)


def clear_config():
    try:
        os.remove(_cfg_path())
    except OSError:
        pass


# ════════════════════════════════════════════════════════════
# 1. DNS guard (AUDIT auto #2): a repeated "Copy Hostname" does not clobber the thread
# ════════════════════════════════════════════════════════════
print("== §1 DNS guard: second 'Copy Hostname' is ignored ==")

clear_config()
win = MW.MainWindow()
node = win.scene.add_server(ServerData(id="rc1-dns", alias="rc1", host="192.0.2.55", user="root"))

_orig_dns_cls = diag.ReverseDnsThread
diag.ReverseDnsThread = _HangingDnsThread   # the seam: the import inside _copy_node_info — by module
th1 = th3 = None
try:
    # The first "Copy Hostname" — the thread starts and hangs (an unreachable resolver).
    win._copy_node_info(node, "hostname")
    th1 = win._dns_thread
    wait_until(lambda: th1 is not None and th1.isRunning(), timeout_ms=3000)
    check("the first Copy Hostname: ReverseDnsThread is running",
          th1 is not None and th1.isRunning())
    check("the thread is created with parent=MainWindow (v1.2.10rc1)", th1.parent() is win,
          repr(th1.parent()))

    # A second fast "Copy Hostname" — the guard: no clobbering + a status message.
    win._copy_node_info(node, "hostname")
    check("guard: self._dns_thread is NOT clobbered (a single thread)", win._dns_thread is th1,
          repr(win._dns_thread))
    _expected_guard = win.t("status.import_resolving", done=0, total=1)
    check("guard: the status message is shown (an existing key — no new i18n)",
          win.statusBar().currentMessage() == _expected_guard,
          win.statusBar().currentMessage())

    # Finishing: release → resolved → the clipboard + cleanup of self._dns_thread.
    th1.release()
    wait_until(lambda: win._dns_thread is None, timeout_ms=5000)
    check("after finished(): self._dns_thread is cleared", win._dns_thread is None)
    check("the resolved name is copied to the clipboard", QApplication.clipboard().text() == "192.0.2.55",
          QApplication.clipboard().text())

    # The guard is lifted: the next request starts a NEW thread.
    win._copy_node_info(node, "hostname")
    th3 = win._dns_thread
    wait_until(lambda: th3 is not None and th3.isRunning(), timeout_ms=3000)
    check("after completion: the next Copy Hostname starts a new thread",
          th3 is not None and th3 is not th1 and th3.isRunning())
finally:
    for _th in (th1, th3):   # release() ALWAYS — an unclosed fake gives no warning on exit
        if _th is not None:
            try:
                _th.release()
            except RuntimeError:
                pass
    diag.ReverseDnsThread = _orig_dns_cls


# ════════════════════════════════════════════════════════════
# 2. closeEvent with a hanging DNS thread (a verification finding):
#    the window closes within the budget, the thread stays in the orphan registry until finished()
# ════════════════════════════════════════════════════════════
print("== §2 closeEvent + hanging DNS thread → orphan registry ==")

clear_config()
win2 = MW.MainWindow()
fake = _HangingDnsThread("192.0.2.77", parent=win2)
win2._dns_thread = fake   # simulating a request stuck on an unreachable resolver
fake.start()
wait_until(lambda: fake.isRunning(), timeout_ms=3000)

try:
    _t0 = time.monotonic()
    win2.close()
    _elapsed = time.monotonic() - _t0

    check("the window closed within the wait budget (~2 s): closeEvent did not hang",
          _elapsed < 4.0, f"{_elapsed:.2f}s")
    check("closeEvent really waited for the budget (the thread is still alive)",
          _elapsed >= 1.8, f"{_elapsed:.2f}s")
    check("the surviving thread is in the orphan registry of services.diagnostics (not left to the GC)",
          fake in diag._orphan_threads and fake.isRunning(),
          f"registry={len(diag._orphan_threads)} running={fake.isRunning()}")

    fake.release()
    wait_until(lambda: fake not in diag._orphan_threads, timeout_ms=8000)
    check("the registry self-cleans on finished()",
          fake not in diag._orphan_threads and not fake.isRunning(),
          f"registry={len(diag._orphan_threads)} running={fake.isRunning()}")
finally:
    try:   # release() ALWAYS — an unclosed fake gives no warning on process exit
        fake.release()
    except RuntimeError:
        pass


# ════════════════════════════════════════════════════════════
# 3. Shutdown: the "ask" gate is skipped (AUDIT manual #1, a real bug)
# ════════════════════════════════════════════════════════════
print("== §3 shutdown with terminal_close_behavior='ask': zero dialogs ==")

write_config({"terminal_close_behavior": "ask"})

_orig_term_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _BlockingTermThread   # the seam: the thread class — from the ssh_terminal module
# ZERO dialogs on the shutdown: QMessageBox.question is replaced ONCE (the seam
# ST.QMessageBox — the same class as MW.QMessageBox: the attribute is set on the class itself,
# every QMessageBox.question call in the process goes here). Before the fix there were exactly
# 2 calls — one "ask" dialog per active session (AUDIT manual #1).
_asked = []
_orig_q = ST.QMessageBox.question
ST.QMessageBox.question = staticmethod(
    lambda *a, **k: (_asked.append(a), QMessageBox.Close)[1])
th_a = th_b = None
try:
    win3 = MW.MainWindow()
    winA = ST.SSHTerminalWindow(
        ServerData(id="rc1-ta", alias="ta", host="10.99.1.1", user="root"), None, password="pw")
    winB = ST.SSHTerminalWindow(
        ServerData(id="rc1-tb", alias="tb", host="10.99.1.2", user="root"), None, password="pw")
    # the compat property window.page — a live reference to the ACTIVE tab: after closing
    # of the last tab it would return None — we store the pages explicitly BEFORE close().
    page_a, page_b = winA.page, winB.page
    th_a, th_b = page_a.terminal_thread, page_b.terminal_thread
    wait_until(lambda: th_a.isRunning() and th_b.isRunning(), timeout_ms=3000)
    check("fixture: 2 active terminal sessions (the threads are running)",
          th_a.isRunning() and th_b.isRunning())
    check("fixture: the 'ask' gate is read from the config",
          page_a._close_behavior == "ask" and page_b._close_behavior == "ask")

    win3._terminal_windows.extend([page_a, page_b])   # the MainWindow session registry
    win3.show()
    app.processEvents()

    _t0 = time.monotonic()
    win3.close()
    _elapsed3 = time.monotonic() - _t0

    check("ZERO QMessageBox.question — the 'ask' gate is skipped on the shutdown (before the fix: 2)",
          len(_asked) == 0, f"asked={len(_asked)}")
    check("the main window is closed", not win3.isVisible())
    check("both sessions are shut down (page.shutdown)",
          page_a._shut_down is True and page_b._shut_down is True)
    check("stop() is called on the threads of each session",
          th_a.stop_calls >= 1 and th_b.stop_calls >= 1,
          f"stops={th_a.stop_calls}/{th_b.stop_calls}")
    check("the surviving threads are in ST._orphan_threads (the N4 path of page.shutdown)",
          th_a in ST._orphan_threads and th_b in ST._orphan_threads,
          f"registry={len(ST._orphan_threads)}")
    check("the shutdown fit into a reasonable budget", _elapsed3 < 15.0, f"{_elapsed3:.2f}s")

finally:
    # release() — ALWAYS (even on FAIL): unclosed fakes must not give
    # "QThread: Destroyed while thread is still running" on process exit.
    for _th in (th_a, th_b):
        if _th is not None:
            try:
                _th.release()
            except RuntimeError:
                pass  # The C++ object is already removed — the thread still lives until release/timeout
    if th_a is not None and th_b is not None:
        wait_until(lambda: (not th_a.isRunning()) and (not th_b.isRunning()), timeout_ms=8000)
        check("the ST orphan registry self-cleans on finished()",
              th_a not in ST._orphan_threads and th_b not in ST._orphan_threads,
              f"registry={len(ST._orphan_threads)}")
    ST.QMessageBox.question = _orig_q
    ST.SSHTerminalThread = _orig_term_cls
    clear_config()


# ════════════════════════════════════════════════════════════
# 4. Release state + i18n parity (NO new keys — 427)
# ════════════════════════════════════════════════════════════
print("== §4 release state + i18n parity ==")

langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)
check_release_state(ROOT)

finish()
