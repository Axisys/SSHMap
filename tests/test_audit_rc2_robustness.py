# -*- coding: utf-8 -*-
"""v1.2.10rc2 — Audit: robustness and code hygiene (AUDIT.md manual #5, auto #7, manual #6).

The thematic test of the release (ROADMAP v1.2.10rc2; offscreen/headless — without the network):

§1 server_data_from_dict with an int id (manual #5e): an explicit "id": 123 in the JSON → str("123");
   a missing/empty id — generated as before (the regression); a string id
   passes unchanged.

§2 PingThread with the host "-x" (manual #5d): subprocess.run is NOT called (the mock),
   the signal finished_ping(False, …) — the Windows ping does not support "--", and such
   a host is an invalid DNS name anyway; the guard fires BEFORE the process start.
   The regression: a regular host starts the subprocess as before.

§3 The late worker signals on the destroyed dialog (manual #5c): closeEvent detached
   the worker via setParent(None) (line 497), the C++ object of the dialog is destroyed — the late
   success/error WITHOUT a RuntimeError (the guard in the slot); the worker finishes the connection,
   the late emit is handled by the event loop without a crash.

§4 delete_password with the fake keyring.errors WITHOUT a PasswordDeleteError (manual #6):
   the generic handler, returns False, without a crash; the class is in place → True (the same
   behavior as before the fix); NoKeyringError → True (the regression). The explicit `import keyring`
   in _try_init (auto #7) — a source check.

§5 the file_dups phantom (manual #5b) + the comment to ANSI_ESCAPE_RE (manual #5a):
   the source checks (the code of ANSI_ESCAPE_RE is unchanged — protected by the convention).

§6 The release state + the i18n parity (427 — no NEW keys).

Run:  python tests/test_audit_rc2_robustness.py   (from the project root) or python tests/run_all.py
"""
import os
import re
import sys
import threading
import time
import types

from _common import (bootstrap, check, finish, wait_until,
                     load_i18n_langs, check_i18n_parity, check_release_state)

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from PySide6.QtCore import QThread, Qt, Signal as QtSignal
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

import keyring as _kr_mod
import subprocess as _subprocess
import services.diagnostics as diag
from models.server import ServerData, server_data_from_dict
from services.credential_manager import CredentialManager


# ════════════════════════════════════════════════════════════
# 1. server_data_from_dict: int id → str (AUDIT manual #5e)
# ════════════════════════════════════════════════════════════
print("== §1 server_data_from_dict: int id → str ==")

d = server_data_from_dict({"id": 123, "alias": "a", "host": "h", "user": "u"})
check("int id 123 → '123' (str)", d.id == "123" and type(d.id) is str, repr(d.id))

d2 = server_data_from_dict({"id": "abcd1234", "alias": "a", "host": "h", "user": "u"})
check("a string id passes through unchanged", d2.id == "abcd1234", repr(d2.id))

d3 = server_data_from_dict({"alias": "a", "host": "h", "user": "u"})
check("a missing id — generated (regression)",
      isinstance(d3.id, str) and len(d3.id) == 8, repr(d3.id))

d4 = server_data_from_dict({"id": "", "alias": "a", "host": "h", "user": "u"})
check("an empty id — generated (regression)",
      isinstance(d4.id, str) and len(d4.id) == 8, repr(d4.id))


# ════════════════════════════════════════════════════════════
# 2. PingThread with the host "-x": the guard BEFORE subprocess (AUDIT manual #5d)
# ════════════════════════════════════════════════════════════
print("== §2 PingThread host '-x': no subprocess ==")


def _run_ping(host):
    """PingThread.run() directly, without start() — the test_diagnostics.py pattern."""
    got = []
    t = diag.PingThread(host)
    t.finished_ping.connect(lambda ok, text: got.append((ok, text)))
    t.run()
    return got


# The host "-x": subprocess must not be launched (the Windows ping does not know "--").
calls = []
_orig_run = _subprocess.run


def _boom(cmd, *a, **k):
    calls.append(cmd)
    raise AssertionError(f"subprocess.run called for the host '-x': {cmd}")


_subprocess.run = _boom
try:
    got = _run_ping("-x")
finally:
    _subprocess.run = _orig_run
check("host '-x': subprocess.run is not called", calls == [])
check("host '-x': finished_ping(False, …)", len(got) == 1 and got[0][0] is False, repr(got))

# Regression: an ordinary host — subprocess launches as before.
calls2 = []


class _FakeProc:
    returncode = 0
    stdout = b""


def _fake_ok(cmd, *a, **k):
    calls2.append(cmd)
    return _FakeProc()


_subprocess.run = _fake_ok
try:
    got2 = _run_ping("192.0.2.7")
finally:
    _subprocess.run = _orig_run
check("an ordinary host: subprocess.run is called once", len(calls2) == 1, repr(calls2))
check("an ordinary host: finished_ping(True, …)", len(got2) == 1 and got2[0][0] is True, repr(got2))
check("the host is on the ping command line", "192.0.2.7" in calls2[0], repr(calls2[0]))


# ════════════════════════════════════════════════════════════
# 3. Late worker signals on a destroyed dialog (AUDIT manual #5c)
# ════════════════════════════════════════════════════════════
print("== §3 late worker signals on destroyed dialog ==")

import dialogs.ssh_connect_dialog as SCD_mod


class _FakeWorker(QThread):
    """The fake SSHWorker (the same signals/the constructor): run() hangs until the release() —
    as the paramiko connection outliving the wait budget of 2 s of the closeEvent."""

    success = QtSignal(str)
    error = QtSignal(str)

    def __init__(self, host, user, port, server_id, password="", key_path="",
                 test_only=False, parent=None):
        super().__init__(parent)
        self.test_only = test_only
        self._release = threading.Event()

    def run(self):
        self._release.wait(30)   # "connection" — it lives longer than the closeEvent budget
        try:
            self.success.emit("late success")
        except RuntimeError:
            pass  # the dialog is destroyed — a late emit without receivers is safe

    def release(self):
        self._release.set()


def _alive(w):
    """Is the C++ object alive (the pattern test_terminal_page.py: after the destruction any
    C++ call on the Python wrapper raises "Internal C++ object already deleted")."""
    try:
        w.windowTitle()
        return True
    except RuntimeError:
        return False


_orig_worker_cls = SCD_mod.SSHWorker
worker = None
try:
    SCD_mod.SSHWorker = _FakeWorker   # the seam: the class name in the dialogs module's namespace
    dlg = SCD_mod.SSHConnectDialog(
        ServerData(id="rc2late", alias="late", host="10.99.8.1", user="root"), None)
    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)   # The C++ object will die after close()
    dlg._start_worker(test_only=False)
    worker = dlg._ssh_worker
    wait_until(lambda: worker is not None and worker.isRunning(), timeout_ms=3000)
    check("fixture: the fake worker is running (parent=the dialog)",
          worker is not None and worker.isRunning() and worker.parent() is dlg,
          repr(worker))

    # Closing the dialog with a live worker: closeEvent waits the ~2 s wait budget and
    # detaches the worker setParent(None) (line 497) — it will outlive the dialog;
    # WA_DeleteOnClose destroys the C++ object after closeEvent.
    _t0 = time.monotonic()
    dlg.close()
    _el = time.monotonic() - _t0
    check("close() waited for the budget (~2 s), did not hang", 1.8 <= _el < 6.0, f"{_el:.2f}s")
    check("the worker is detached: parent == None (setParent(None))", worker.parent() is None)
    wait_until(lambda: not _alive(dlg), timeout_ms=4000)
    check("fixture: the C++ object of the dialog is destroyed", not _alive(dlg))

    # A late success/error on a destroyed dialog: before the fix — a RuntimeError from the slot
    # (PySide prints and swallows in the Qt dispatch), afterwards the guard swallows it silently.
    try:
        dlg._on_worker_success("late success")
        _ok_s, _err_s = True, ""
    except RuntimeError as e:
        _ok_s, _err_s = False, str(e)
    check("a late _on_worker_success on a destroyed dialog — no RuntimeError",
          _ok_s, _err_s)

    try:
        dlg._on_worker_error("late error")
        _ok_e, _err_e = True, ""
    except RuntimeError as e:
        _ok_e, _err_e = False, str(e)
    check("a late _on_worker_error on a destroyed dialog — no RuntimeError",
          _ok_e, _err_e)

    # E2E: the worker outlives the connection and emits a late success from its thread;
    # The Qt connections to the dead dialog are removed on its destruction — delivery is a no-op,
    # the event loop processes everything without crashing the process.
    worker.release()
    wait_until(lambda: not worker.isRunning(), timeout_ms=8000)
    check("the worker has finished, the process is alive (the late emit is handled)", not worker.isRunning())
finally:
    SCD_mod.SSHWorker = _orig_worker_cls
    if worker is not None:
        try:
            worker.release()   # ALWAYS — an unclosed fake gives no warning on exit
        except RuntimeError:
            pass


# ════════════════════════════════════════════════════════════
# 4. delete_password: a fake keyring.errors (AUDIT manual #6 + auto #7)
# ════════════════════════════════════════════════════════════
print("== §4 delete_password with fake keyring.errors ==")


class _FakeBackend:
    """The fake backend: delete_password always raises the given exception."""

    def __init__(self, exc):
        self._exc = exc
        self.calls = 0

    def delete_password(self, service, username):
        self.calls += 1
        raise self._exc("fake failure")


def _make_cm(exc):
    cm = CredentialManager.__new__(CredentialManager)  # past _try_init — the real keyring is not involved
    cm._keyring_backend = _FakeBackend(exc)
    cm._backend_available = True
    return cm


class _NoKeyringError(Exception):
    pass


def _swap_keyring_errors(fake_mod):
    """The replacement of sys.modules['keyring.errors'] AND the attribute of the keyring package (both paths:
    `import keyring.errors` takes from sys.modules, `keyring.errors.X` — through the attribute)."""
    orig_mod = sys.modules.get("keyring.errors")
    orig_attr = getattr(_kr_mod, "errors", None)
    sys.modules["keyring.errors"] = fake_mod
    _kr_mod.errors = fake_mod
    return (orig_mod, orig_attr)


def _restore_keyring_errors(saved):
    orig_mod, orig_attr = saved
    if orig_mod is not None:
        sys.modules["keyring.errors"] = orig_mod
    else:
        sys.modules.pop("keyring.errors", None)
    _kr_mod.errors = orig_attr


# (a) keyring WITHOUT PasswordDeleteError → the generic handler, False, no crash.
fake_a = types.ModuleType("keyring.errors")
fake_a.NoKeyringError = _NoKeyringError   # No PasswordDeleteError on purpose
saved_a = _swap_keyring_errors(fake_a)
try:
    cm_a = _make_cm(RuntimeError)         # a foreign exception — not NoKeyringError
    res_a = cm_a.delete_password("rc2del")
    check("without PasswordDeleteError → the generic handler, returns False",
          res_a is False, repr(res_a))
    check("the backend is called (the exception from delete_password)", cm_a._keyring_backend.calls == 1)
finally:
    _restore_keyring_errors(saved_a)

# (b) keyring WITH PasswordDeleteError → True (the same behaviour as before the fix).
class _PasswordDeleteError(Exception):
    pass


fake_b = types.ModuleType("keyring.errors")
fake_b.NoKeyringError = _NoKeyringError
fake_b.PasswordDeleteError = _PasswordDeleteError
saved_b = _swap_keyring_errors(fake_b)
try:
    cm_b = _make_cm(_PasswordDeleteError)
    res_b = cm_b.delete_password("rc2del")
    check("PasswordDeleteError is present → True (the entry was absent)",
          res_b is True, repr(res_b))
finally:
    _restore_keyring_errors(saved_b)

# (c) NoKeyringError → True (regression of the existing behaviour, the real module).
import keyring.errors as _kre_real
cm_c = _make_cm(_kre_real.NoKeyringError)
res_c = cm_c.delete_password("rc2del")
check("NoKeyringError → True (nothing to delete)", res_c is True, repr(res_c))

# (d) auto #7: the explicit `import keyring` in _try_init — a source check.
_src_cm = open(os.path.join(ROOT, "services", "credential_manager.py"), encoding="utf-8").read()
_m = re.search(r"def _try_init\(self\):(.*?)(?=\n    @property|\n    def )", _src_cm, re.S)
_body = _m.group(1) if _m else ""
check("auto #7: an explicit 'import keyring' in _try_init (not only keyring.errors)",
      re.search(r"^\s+import keyring\s*$", _body, re.M) is not None)


# ════════════════════════════════════════════════════════════
# 5. Hygiene: the file_dups ghost + the ANSI_ESCAPE_RE comment (source)
# ════════════════════════════════════════════════════════════
print("== §5 hygiene: file_dups ghost + ANSI_ESCAPE_RE comment ==")

_src_ops = open(os.path.join(ROOT, "ui", "main_window_node_ops.py"), encoding="utf-8").read()
# The ghost — exactly these two constructs (a comment may mention the history).
check("manual #5b: the file_dups ghost is removed (no code references)",
      "entries, file_dups" not in _src_ops and "len(file_dups)" not in _src_ops)

_src_term = open(os.path.join(ROOT, "modules", "ssh_terminal.py"), encoding="utf-8").read()
_i = _src_term.find("ANSI_ESCAPE_RE = re.compile")
_head = _src_term[max(0, _i - 700):_i] if _i >= 0 else ""
check("manual #5a: ANSI_ESCAPE_RE comment — tests/test_core.py + 'Do not touch'",
      "tests/test_core.py" in _head and "Do not touch" in _head, _head[-200:])


# ════════════════════════════════════════════════════════════
# 6. Release state + i18n parity (427 — NO new keys)
# ════════════════════════════════════════════════════════════
print("== §6 release state + i18n parity ==")

langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)
check_release_state(ROOT)

finish()
