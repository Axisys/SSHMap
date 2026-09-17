# -*- coding: utf-8 -*-
"""v1.1.4: main_window.py hygiene — split into mixins (ROADMAP v1.1.4 acceptance).

The thematic test of the split: the offscreen MainWindow + the run of each cluster:
  * the structure: all the methods of the plan are defined in ProjectIOMixin/NodeOpsMixin/SshMixin
    (not in MainWindow.__dict__), the MRO order, the mixins do NOT import main_window
    (the cycle), the seam host_attr sees the swaps of the facade module (MW.<name> = Fake);
  * ProjectIOMixin: the save/load/restore — _save_project_as → _autosave_tick →
    _restore_from_autosave → _load_project_at in the second window;
  * NodeOpsMixin: the add/duplicate/delete of a node — _add_server (the fake AddServerDialog,
    including the bool guard v0.8.1), _duplicate_selected_node, the group _delete_selected_nodes;
  * SshMixin: the ssh-dialog flow — _run_ssh_connect with the fakes of the SSHConnectDialog/
    SSHTerminalWindow: the fields via the undo stack, the indicator, the registry of the windows,
    _forget_terminal_window; the quick launch lives in the same mixin.

Run: python tests/test_main_window_split.py   (from the project root) or python tests/run_all.py
"""
import json
import os
import re
import sys

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QFileDialog

app = QApplication(sys.argv)

# Network is forbidden in tests: the status probes return the result instantly
# (otherwise _load_project_at → start_round would spawn threads with network timeouts).
import services.status_checker as _SC
_SC.probe_ssh = lambda host, port, timeout=3.0: "offline"

from storage import autosave as AS
from models.server import ServerData
from modules.undo_commands import CmdEditNodeData
import ui.main_window as MW
import ui.main_window_project_io as PI
import ui.main_window_node_ops as NO
import ui.main_window_ssh as SS
from ui.mixin_support import host_attr

# ── QMessageBox: no modals in offscreen, the calls are logged; question — controlled ──
boxes = []
question_replies = []  # the queue of the ready answers for question()


def _fake_question(*a, **k):
    boxes.append(("question", str(a[1]) if len(a) > 1 else ""))
    return question_replies.pop(0) if question_replies else QMessageBox.Yes


# QMessageBox — one class for all modules (main_window and the mixins import it
# from PySide6): the patch via MW.QMessageBox works everywhere, including the moved methods.
MW.QMessageBox.question = staticmethod(_fake_question)
MW.QMessageBox.critical = staticmethod(lambda *a, **k: boxes.append(("critical", str(a[1]), str(a[2]))))
MW.QMessageBox.warning = staticmethod(lambda *a, **k: boxes.append(("warning", str(a[1]), str(a[2]))))
MW.QMessageBox.information = staticmethod(lambda *a, **k: boxes.append(("information", str(a[1]), str(a[2]))))


def make_window():
    """An offscreen MainWindow with a stopped autosave timer (we call the ticks by hand)."""
    win = MW.MainWindow()
    win._autosave_timer.stop()  # the determinism: _autosave_tick below is called explicitly
    return win


# ══ 1. The structure: the clusters in the mixins, MainWindow — the facade ═══════════════════
print("== 1. structure: clusters live in mixins ==")

_mro = [c.__name__ for c in MW.MainWindow.__mro__]
check("MRO: MainWindow → ProjectIOMixin → NodeOpsMixin → SshMixin → QMainWindow",
      _mro[:5] == ["MainWindow", "ProjectIOMixin", "NodeOpsMixin", "SshMixin", "QMainWindow"],
      str(_mro[:6]))

# The full list of the plan methods (ROADMAP v1.1.4, tasks 1–3; quick launch — in the SSH cluster)
PLAN = {
    "ProjectIOMixin": [
        "_new_project", "_import_project_raw", "_open_project", "_load_project_at",
        "_save_project", "_save_project_as", "_serialize_project_data", "_do_save",
        "_autosave_tick", "_restore_from_autosave", "_backup_items",
        "_show_backups_dialog", "_restore_from_source",
    ],
    "NodeOpsMixin": [
        "_add_server", "_import_servers_from_txt", "_duplicate_node",
        "_duplicate_selected_node", "_delete_selected_nodes", "_remove_node_guarded",
        "_ensure_worker_done", "_connect_selected_nodes", "_add_connection",
        "_edit_connection", "_remove_connection", "_copy_node_info", "_ping_node",
    ],
    "SshMixin": [
        "_connect_ssh_to_selected", "_run_ssh_connect", "_spawn_terminal_window",
        "_forget_terminal_window", "_apply_ssh_dialog_fields", "_connect_ssh_external",
        "_collect_node_info", "_on_info_ready", "_on_info_failed",
        "_open_quick_launch_dialog", "_run_quick_launch_entry",
        "_quick_launch_url", "_quick_launch_command",
    ],
}

_bad = []
for mixin_name, methods in PLAN.items():
    for m in methods:
        fn = getattr(MW.MainWindow, m, None)
        if fn is None:
            _bad.append(f"{m}: missing")
        elif m in MW.MainWindow.__dict__:
            _bad.append(f"{m}: still in MainWindow.__dict__")
        elif fn.__qualname__.split(".")[0] != mixin_name:
            _bad.append(f"{m}: owner {fn.__qualname__}")
check(f"all the planned methods ({sum(len(v) for v in PLAN.values())}) are defined in their own mixins",
      not _bad, "; ".join(_bad[:6]))

# AUDIT §3: the mixins do NOT import main_window (a cycle) — duck typing only.
_circ = []
for mod in (PI, NO, SS):
    with open(mod.__file__, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if re.match(r"\s*(from|import)\b", line) and "main_window" in line:
                _circ.append(f"{os.path.basename(mod.__file__)}:{i}: {line.strip()}")
check("the mixins do not import main_window (no cycle)", not _circ, "; ".join(_circ))

win0 = make_window()
check("host_attr sees the facade module's attribute",
      host_attr(win0, "SSHConnectDialog") is MW.SSHConnectDialog)


class _Sentinel:  # the substitution marker
    pass


_orig_dlg = MW.SSHConnectDialog
MW.SSHConnectDialog = _Sentinel
try:
    check("host_attr sees the test replacement (the seam for offscreen)",
          host_attr(win0, "SSHConnectDialog") is _Sentinel)
finally:
    MW.SSHConnectDialog = _orig_dlg

# ══ 2. ProjectIOMixin: save / load / restore ════════════════════════════════
print("== 2. ProjectIOMixin: save/load/restore ==")

path = os.path.join(WORK, "split_io.json")
win0.scene.add_server(ServerData(id="splita1", alias="SplitA", host="10.6.0.1", user="root"))
win0.scene.add_server(ServerData(id="splitb2", alias="SplitB", host="10.6.0.2", user="root"))
win0._mark_dirty()

_orig_savefn = QFileDialog.getSaveFileName
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (path, ""))
try:
    saved = win0._save_project_as()
finally:
    QFileDialog.getSaveFileName = _orig_savefn
check("_save_project_as: saved, _project_file is set",
      saved is True and win0._project_file == path)
check("_save_project_as: the dirty flag is reset",
      not win0._dirty and " [*]" not in win0.windowTitle(), win0.windowTitle())
with open(path, encoding="utf-8") as f:
    disk = json.load(f)
check("the JSON on disk: the two nodes (no passwords)",
      {s["id"] for s in disk["servers"]} == {"splita1", "splitb2"}
      and all(not s.get("password") for s in disk["servers"]), str(disk["servers"]))

# the autosave: the third node + a manual tick (the timer is stopped)
win0.scene.add_server(ServerData(id="splitc3", alias="SplitC", host="10.6.0.3", user="root"))
win0._mark_dirty()
win0._autosave_tick()
auto_path = AS.autosave_path_for(path)
check("_autosave_tick: the autosave file appears", os.path.isfile(auto_path), auto_path)

# restore: the third node is deleted from memory, restored from the autosave
win0.scene.remove_server("splitc3")
question_replies.append(QMessageBox.Yes)  # the restoration confirmation
win0._restore_from_autosave()
check("_restore_from_autosave: the scene is back to three nodes",
      win0.scene.node_count() == 3, str(win0.scene.node_count()))
with open(path, encoding="utf-8") as f:
    disk2 = json.load(f)
check("restore: the autosave content is written to the project file",
      {s["id"] for s in disk2["servers"]} == {"splita1", "splitb2", "splitc3"},
      str([s["id"] for s in disk2["servers"]]))

# a load in the second window (the shared File→Open path)
win2 = make_window()
loaded = win2._load_project_at(path)
check("_load_project_at: loaded, _project_file is set",
      loaded is True and win2._project_file == path)
check("_load_project_at: the nodes are restored, the dirty flag is reset",
      win2.scene.node_count() == 3 and not win2._dirty,
      f"nodes={win2.scene.node_count()} dirty={win2._dirty}")

# ══ 3. NodeOpsMixin: add / duplicate / delete node ══════════════════════════
print("== 3. NodeOpsMixin: add/duplicate/delete ==")

winN = make_window()
winN.show()
app.processEvents()


class _FakeAddDlg:
    """The fake AddServerDialog: it is replaced on the facade module (MW.AddServerDialog),
    the mixin takes it through the host_attr at the moment of the call."""
    instances = []

    def __init__(self, parent=None):
        self._data = ServerData(
            id=f"splitadd{len(_FakeAddDlg.instances) + 1:02d}",
            alias="SplitAdd", host="10.7.0.1", user="root")
        self._connect_after_accept = False
        _FakeAddDlg.instances.append(self)

    def exec(self):
        return QDialog.Accepted

    def get_data(self):
        return self._data


_orig_add = MW.AddServerDialog
MW.AddServerDialog = _FakeAddDlg
try:
    winN._add_server()      # the toolbar path (without a position)
    winN._add_server(True)  # the v0.8.1 regression: a bool from QAction.triggered — no crash
finally:
    MW.AddServerDialog = _orig_add
check("_add_server (the mixin): two nodes on the scene", winN.scene.node_count() == 2,
      str(winN.scene.node_count()))
check("_add_server: the dirty flag + one undo command for the node",
      winN._dirty and winN.undo_stack.count() == 2,
      f"dirty={winN._dirty} undo={winN.undo_stack.count()}")

# duplicating the selected (Ctrl+D)
na = winN.scene.get_node("splitadd01")
winN._select_node(na)
ndup = winN._duplicate_selected_node()
check("_duplicate_selected_node: the copy is created (a new id, the same fields)",
      ndup is not None and ndup.data.id != "splitadd01"
      and ndup.data.alias == "SplitAdd" and ndup.data.host == "10.7.0.1",
      f"id={ndup.data.id if ndup else None}")
check("the duplicate is offset by +40/+40",
      ndup is not None
      and abs(ndup.data.x - na.data.x - 40.0) < 1e-6
      and abs(ndup.data.y - na.data.y - 40.0) < 1e-6,
      f"orig=({na.data.x},{na.data.y}) dup=({ndup.data.x if ndup else None},{ndup.data.y if ndup else None})")
check("the duplicate is selected", winN.scene.get_selected_node() is ndup)

# a group removal of all three (one question for the whole group)
for node in winN.scene.nodes():
    node.setSelected(True)
check("the multi-selection: three nodes are selected", len(winN.selected_nodes()) == 3,
      str(len(winN.selected_nodes())))
question_replies.append(QMessageBox.Yes)
ok = winN._delete_selected_nodes()
check("_delete_selected_nodes (the mixin): all are deleted",
      ok is True and winN.scene.node_count() == 0, str(winN.scene.node_count()))
check("the bulk delete: the dirty flag is set", winN._dirty)

# ══ 4. SshMixin: ssh-dialog flow ════════════════════════════════════════════
print("== 4. SshMixin: ssh-dialog flow ==")

winS = make_window()
winS.show()
app.processEvents()
ns = winS.scene.add_server(
    ServerData(id="splitssh1", alias="SplitSSH", host="10.8.0.1", user="root"))


from _fakes import FakeLineEdit as _FL, FakeSpinBox as _FS, FakeTermWin as _FakeTermWin


class _FakeSSHDialog:
    def __init__(self, data, parent=None):
        self.user_edit = _FL("split-user")
        self.key_path_edit = _FL("/keys/split.pem")
        self.port_edit = _FS(2244)
        self.password_edit = _FL("SplitPw123")

    def exec(self):
        return QDialog.Accepted


spawned_terms = []
_FakeTermWin.spawned = spawned_terms   # the window fake records the created windows (_fakes)


# the auto collection of information — we log it instead of the real collector (network is forbidden in tests)
collect_calls = []
winS._collect_node_info = lambda node, password="", auto=False: \
    collect_calls.append((node.data.id, password, auto))

_orig_sshdlg, _orig_termwin = MW.SSHConnectDialog, MW.SSHTerminalWindow
MW.SSHConnectDialog = _FakeSSHDialog
MW.SSHTerminalWindow = _FakeTermWin
try:
    winS._run_ssh_connect(ns)
finally:
    MW.SSHConnectDialog = _orig_sshdlg
    MW.SSHTerminalWindow = _orig_termwin

check("ssh flow: the dialog's fields are applied to the node (_apply_ssh_dialog_fields)",
      ns.data.user == "split-user" and ns.data.ssh_port == 2244
      and ns.data.key_path == "/keys/split.pem",
      f"user={ns.data.user!r} port={ns.data.ssh_port} key={ns.data.key_path!r}")
_top = winS.undo_stack.command(winS.undo_stack.count() - 1) if winS.undo_stack.count() else None
check("ssh flow: the fields go through the undo stack (CmdEditNodeData)",
      isinstance(_top, CmdEditNodeData), f"{type(_top).__name__ if _top else None}")
check("ssh flow: the node is in _ssh_connected_nodes (the connection indicator)",
      ns.data.id in winS._ssh_connected_nodes)
check("ssh flow: the terminal window is created and registered",
      len(spawned_terms) == 1 and len(winS._terminal_windows) == 1,
      f"spawned={len(spawned_terms)} registry={len(winS._terminal_windows)}")
if spawned_terms:
    check("ssh flow: the password is passed to the window, not stored in the model",
          spawned_terms[0].password == "SplitPw123" and ns.data.password == "")
check("ssh flow: the auto-info gathering after the connection (auto=True, with the password)",
      collect_calls == [("splitssh1", "SplitPw123", True)], str(collect_calls))
winS._forget_terminal_window(spawned_terms[0])
check("_forget_terminal_window: the registry is cleared", winS._terminal_windows == [])

# without a selection — an information message, no crash
boxes.clear()
winS.scene.clear_all()
winS._connect_ssh_to_selected()
check("no selection: the information is shown, no exception",
      any(b[0] == "information" for b in boxes), str(boxes))

finish()
