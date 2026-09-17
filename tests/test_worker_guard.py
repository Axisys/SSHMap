"""SSHWorker: the active threads registry + the node deletion guard (former smoke_test.py §6c).

A part of the suite split out of smoke_test.py v0.6–v0.9.2 (see INDEX.md).
  * the registry: the worker is visible after construction, gone on finished;
  * wait_for_worker: an unstarted thread → True instantly (the guard does not block the removal),
    an unknown id → True;
  * MainWindow._ensure_worker_done — the single guard for the node removal;
  * SSHConnectDialog.closeEvent waits for the thread before closing the dialog.

Run: python tests/test_worker_guard.py   (from the project root) or python tests/run_all.py
"""
# tags: slow
# the reason: waiting for the workers to finish (the wait budgets — part of the specification)

import sys

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

import ui.main_window as MW
from models.server import ServerData

# ── v0.6.x patch: SSHWorker registry + delete guard ───────
print("== v0.6.x worker guard ==")
from modules.ssh_worker import (
    SSHWorker as _SW, get_active_worker as _gaw, wait_for_worker as _wfw,
)

# 1) Registry: created → present; finished → not visible. A real fast
# a failure (127.0.0.1:9 — connection refused), the thread finishes by itself in <1 s.
w_g = _SW(host="127.0.0.1", user="u", port=9, server_id="guardtest")
check("worker registered in active registry on construction", _gaw("guardtest") is w_g)
# wait() on an unstarted thread returns true instantly per Qt — the guard does not block the removal
check("wait_for_worker: never-started worker -> True immediately", _wfw("guardtest", 500) is True)
# we start for real, to check the registry auto-cleanup on finished:
w_g2s = _SW(host="127.0.0.1", user="u", port=9, server_id="guardrun")
w_g2s.start()
check("started worker finishes (fast refused) and leaves registry",
      w_g2s.wait(3000) is True and _gaw("guardrun") is None)
# w_g is not started — we remove it from the registry by hand so it does not pollute the later checks
from modules.ssh_worker import _active_workers as _aw_reg
_aw_reg.pop("guardtest", None)
check("wait_for_worker for unknown id -> True", _wfw("no-such-id", 100) is True)

# 2) MainWindow._ensure_worker_done — the single guard for node deletion
win4 = MW.MainWindow()
ndg = ServerData(id="guardnode", alias="gn", host="127.0.0.1", user="u")
win4.scene.add_server(ndg)
check("_ensure_worker_done passes when no running worker", win4._ensure_worker_done("guardnode") is True)

# 3) SSHConnectDialog.closeEvent waits for the thread before closing the dialog:
# close() on a hidden widget may not deliver the event — we call closeEvent directly.
from dialogs.ssh_connect_dialog import SSHConnectDialog as _SCD2
from PySide6.QtGui import QCloseEvent as _QCE

sdlg = _SCD2(ndg, None)
w_g3 = _SW(host="127.0.0.1", user="u", port=9, server_id="guardclose")
w_g3.start()
sdlg._ssh_worker = w_g3
_ev_close = _QCE()  # PySide6 6.11: a no-argument constructor (Qt5 style)
sdlg.closeEvent(_ev_close)
check("dialog closeEvent waits for SSHWorker to finish", not w_g3.isRunning())
check("closeEvent accepts the close after worker done", _ev_close.isAccepted() is True)

finish()
