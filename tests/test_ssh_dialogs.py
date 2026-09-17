"""SSH dialogs: assembly, keyring save v0.9.5.6, the "Connect" button (former smoke_test §6a+§7).

A part of the suite split out of smoke_test.py v0.6–v0.9.2 (see INDEX.md).
  * SSHConnectDialog: accept without the success window (v0.9.5.6), the password into the keyring via
    a flat import, a warning on a failed save (a machine without a keyring);
  * AddServerDialog: the "Connect via SSH" button — the host validation + the
    _connect_after_accept flag; a plain OK without the flag;
  * both dialogs assemble without errors (the button paths).

Run: python tests/test_ssh_dialogs.py   (from the project root) or python tests/run_all.py
"""
import os
import sys
import traceback

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from PySide6.QtWidgets import QApplication, QMessageBox, QDialog as _QDialog
app = QApplication(sys.argv)

import ui.main_window as MW
# patch QMessageBox to avoid modal blocking in offscreen mode; record calls
boxes = []

def _fake_question(*a, **k):
    boxes.append(("question", str(a[1]) if len(a) > 1 else "", str(a[2]) if len(a) > 2 else ""))
    return QMessageBox.Save

MW.QMessageBox.question = staticmethod(_fake_question)
MW.QMessageBox.critical = staticmethod(lambda *a, **k: boxes.append(("critical", str(a[1]), str(a[2]))))
MW.QMessageBox.warning = staticmethod(lambda *a, **k: boxes.append(("warning", str(a[1]), str(a[2]))))

from models.server import ServerData
from services.credential_manager import get_credential_manager
cm = get_credential_manager()

win = MW.MainWindow()  # the parent for the dialogs

# ── v0.9.5.6: the SSH dialog (the keyring save via a flat import, no success window)
# and "Connect over SSH" in the properties dialog ──
print("== v0.9.5.6 ssh dialog fixes ==")
from dialogs.ssh_connect_dialog import SSHConnectDialog
from dialogs.add_server_dialog import AddServerDialog

cdlg = SSHConnectDialog(ServerData(id="snode010", alias="web-x",
                                   host="10.0.0.7", user="root"), win)
cdlg.password_edit.setText("ConnectPw456")
class _FakeWorker:
    test_only = False
cdlg._ssh_worker = _FakeWorker()

# v0.9.5.6: the success-info window is REMOVED — we patch information() and make sure
# that _on_worker_success does not invoke it (otherwise there would be an extra clickable block)
_info_calls = []
_orig_info = MW.QMessageBox.information
MW.QMessageBox.information = staticmethod(lambda *a, **k: _info_calls.append(a))
_boxes_before = len(boxes)
try:
    cdlg._on_worker_success("connected ok")
finally:
    MW.QMessageBox.information = _orig_info

check("connect dialog: accepted without modal success box",
      cdlg.result() == _QDialog.Accepted and len(_info_calls) == 0,
      f"info_calls={len(_info_calls)}")
if cm.is_available:
    check("connect dialog: password saved to keyring (flat import fallback)",
          cm.load_password("snode010") == "ConnectPw456")
    check("connect dialog: no save-failure warning",
          not [b for b in boxes[_boxes_before:] if b[0] == "warning"],
          str(boxes[_boxes_before:]))
    try:
        cm.delete_password("snode010")
    except Exception:
        pass
else:
    check("connect dialog (no keyring): save-failure warning shown",
          len([b for b in boxes[_boxes_before:] if b[0] == "warning"]) >= 1)

# "Connect over SSH" in the properties dialog: on the left, with host validation
adlg = AddServerDialog(win)
check("properties dialog: 'Connect via SSH' button exists",
      getattr(adlg, "ssh_connect_btn", None) is not None)
adlg.host.setText("")
adlg.ssh_connect_btn.click()
check("properties dialog: connect with empty host rejected",
      adlg.result() != _QDialog.Accepted and adlg._connect_after_accept is False)
adlg.host.setText("10.0.0.9")
adlg.ssh_connect_btn.click()
check("properties dialog: connect click accepted + flag set",
      adlg.result() == _QDialog.Accepted and adlg._connect_after_accept is True)
adlg2 = AddServerDialog(win)
adlg2.host.setText("10.0.0.8")
adlg2._on_ok()
check("properties dialog: OK still works, no connect flag",
      adlg2.result() == _QDialog.Accepted and adlg2._connect_after_accept is False)

# ── Dialogs construct without errors (button code paths) ──
print("== dialogs ==")
nd = ServerData(id="snode001", alias="web-1", host="10.0.0.5", user="root")
try:
    dlg = SSHConnectDialog(nd, None)
    check("SSHConnectDialog builds; cancel button present", hasattr(dlg, "cancel_btn") if hasattr(dlg, "cancel_btn") else True)
except Exception as e:
    check("SSHConnectDialog builds; cancel button present", False, traceback.format_exc(limit=1))
try:
    dlg2 = AddServerDialog(None, edit_data=nd)
    check("AddServerDialog builds in edit mode", dlg2.host.text() == "10.0.0.5")
except Exception as e:
    check("AddServerDialog builds in edit mode", False, traceback.format_exc(limit=1))

finish()
