"""Regression v0.9.7 — autosave + the project backup ring buffer.

ROADMAP v0.9.7:
  #1 the autosave into ~/.sshmap/autosave/ (the interval from the config, the default ~60 s,
     only when dirty and with the open project file).
  #2 the ring buffer of the backups (N files, the default 10) at every manual save —
     the rollback to the previous versions of the file.
  #3 the recovery on the open: if the autosave is newer than the file — the offer
     to restore it (before the replacement of the content).

Run:  python tests/test_autosave_backups.py   (from the project root) or python tests/run_all.py
"""
import json
import os
import sys
import tempfile
import time as _time

from _common import bootstrap, check, finish, load_i18n_langs, check_i18n_parity

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication(sys.argv)

# Network is forbidden in tests: the status probes return the result instantly
# (otherwise _load_project_at → start_round would spawn threads with network timeouts).
import services.status_checker as _SC
_SC.probe_ssh = lambda host, port, timeout=3.0: "offline"

import storage.autosave as A
from i18n import t as it, save_config
from models.server import ServerData
import ui.main_window as MW

import shutil
WORK = os.path.join(ROOT, "_tmp_testdata_v097")
shutil.rmtree(WORK, ignore_errors=True)  # a clean start (the smoke_test pattern): leftovers from past runs must not interfere
os.makedirs(WORK, exist_ok=True)
# v1.1.2 final (N12): on EXIT the directory is cleaned up too (rmtree before finish() below) —
# after the suite run nothing is left on disk.

# ══ storage.autosave: a pure module (no Qt) ════════════════════════════════
print("== project_key ==")
_orig_cwd = os.getcwd()
try:
    k_abs = A.project_key(os.path.join(WORK, "map.json"))
    os.chdir(WORK)
    k_rel = A.project_key("map.json")
finally:
    os.chdir(_orig_cwd)
check("project_key: a relative and an absolute path → one key", k_abs == k_rel,
      f"{k_abs} vs {k_rel}")
check("project_key: different directories → different keys (same-named files)",
      A.project_key(os.path.join(WORK, "a.json")) != A.project_key(os.path.join(WORK, "sub", "a.json")))

print("== autosave round-trip ==")
p = os.path.join(WORK, "rt", "map.json")
os.makedirs(os.path.dirname(p), exist_ok=True)
with open(p, "w", encoding="utf-8") as f:
    json.dump({"version": "0.9", "servers": []}, f)
A.write_autosave(p, {"version": "0.9", "servers": [{"id": "x"}]})
check("write_autosave → a file in ~/.sshmap/autosave/", os.path.isfile(A.autosave_path_for(p)),
      A.autosave_path_for(p))
data = A.read_autosave(p)
check("read_autosave round-trip (the content matches)",
      data is not None and data["servers"] == [{"id": "x"}], str(data))
with open(A.autosave_path_for(p), "w", encoding="utf-8") as f:
    f.write("{not json")
check("a corrupt autosave → read_autosave None (no exception)", A.read_autosave(p) is None)

print("== autosave_is_newer ==")
now = _time.time()
os.utime(A.autosave_path_for(p), (now - 100, now - 100))
os.utime(p, (now, now))
check("an autosave OLDER than the file → not 'fresh'", A.autosave_is_newer(p) is False)
os.utime(A.autosave_path_for(p), (now + 100, now + 100))
check("an autosave NEWER than the file → 'fresh' (ROADMAP #3)", A.autosave_is_newer(p) is True)

print("== rotate_backups: the ring buffer ==")
q = os.path.join(WORK, "ring", "map.json")
os.makedirs(os.path.dirname(q), exist_ok=True)

def _save(v):
    with open(q, "w", encoding="utf-8") as f:
        json.dump({"v": v}, f)

def _slot(n):
    with open(A.backup_path_for(q, n), encoding="utf-8") as f:
        return json.load(f)["v"]

# 5 saves at N=3: every save precedes the rotate "before" the overwrite
_save("v1"); A.rotate_backups(q, 3)
_save("v2"); A.rotate_backups(q, 3)
_save("v3"); A.rotate_backups(q, 3)
_save("v4"); A.rotate_backups(q, 3)
_save("v5")
check("ring N=3: slot1 = the version before the current one (v4)", _slot(1) == "v4", str(_slot(1)))
check("ring N=3: slot2 = v3", _slot(2) == "v3", str(_slot(2)))
check("ring N=3: slot3 = v2", _slot(3) == "v2", str(_slot(3)))
check("ring N=3: the overflow (v1) is removed — no slot 4",
      not os.path.isfile(A.backup_path_for(q, 4)))
with open(q, encoding="utf-8") as f:
    check("the project file = the current version (v5)", json.load(f)["v"] == "v5")

items = A.list_backups(q, 3)
check("list_backups: the newest first, exactly 3 entries", [i["slot"] for i in items] == [1, 2, 3],
      str([i["slot"] for i in items]))
check("list_backups: mtime/size are present", all(i["mtime"] > 0 and i["size"] > 0 for i in items))

print("== restore_to_project ==")
A.restore_to_project(A.backup_path_for(q, 3), q)  # v2 back into the file
with open(q, encoding="utf-8") as f:
    check("restore copies the backup back into the project file", json.load(f)["v"] == "v2")
check("the source backup is untouched after the restore", _slot(3) == "v2")
try:
    A.restore_to_project(os.path.join(WORK, "nope.json"), q)
    check("a missing source → FileNotFoundError", False, "no exception raised")
except FileNotFoundError:
    check("a missing source → FileNotFoundError", True)

print("== get_autosave_settings (the config ~/.sshmap/config.json) ==")
s = A.get_autosave_settings()
check("defaults: on / 60 s / 10 backups (ROADMAP v0.9.7)",
      s == {"enabled": True, "interval_sec": 60, "backup_count": 10}, str(s))
save_config({"autosave_enabled": False, "autosave_interval_sec": "abc", "backup_count": -5})
s2 = A.get_autosave_settings()
check("broken values → the default/boundary (enabled=False is read)",
      s2 == {"enabled": False, "interval_sec": 60, "backup_count": 1}, str(s2))
save_config({"autosave_enabled": True, "autosave_interval_sec": 30, "backup_count": 5})
s3 = A.get_autosave_settings()
check("custom values from the config (30 s / 5 backups)",
      s3["enabled"] is True and s3["interval_sec"] == 30 and s3["backup_count"] == 5, str(s3))

# ══ MainWindow: the manual saves → the ring buffer ═══════════════════════════════
print("== MainWindow: save → backups ==")
win = MW.MainWindow()
win.show(); app.processEvents()
view = win.view
view.resize(900, 700); app.processEvents()

proj_dir = os.path.join(WORK, "app")
os.makedirs(proj_dir, exist_ok=True)
proj_path = os.path.join(proj_dir, "map.json")

win.scene.add_server(ServerData(id="a7b1", alias="web-1", host="127.0.0.1", user="ops", x=100, y=100))
win.scene.add_server(ServerData(id="a7b2", alias="db-1", host="127.0.0.1", user="dba", x=300, y=100))
win._dirty = True
check("the first save of a new file succeeds", win._do_save(proj_path) is True)
# like _save_project_as: a successful save-as remembers the project file
win._project_file = proj_path
with open(proj_path, encoding="utf-8") as f:
    check("the file is written (2 servers)", len(json.load(f)["servers"]) == 2)
check("the first save: no backups yet (there was no previous version)", A.list_backups(proj_path) == [])

win.scene.add_server(ServerData(id="a7b3", alias="cache-1", host="127.0.0.1", user="redis", x=500, y=100))
win._dirty = True
check("the second save succeeds", win._do_save(proj_path) is True)
slots = A.list_backups(proj_path)
with open(slots[0]["path"], encoding="utf-8") as f:
    check("after the 2nd save: slot1 = the previous version (2 servers)",
          len(slots) == 1 and len(json.load(f)["servers"]) == 2, str([i["slot"] for i in slots]))

win.scene.add_server(ServerData(id="a7b4", alias="mq-1", host="127.0.0.1", user="mq", x=700, y=100))
win._dirty = True
check("the third save succeeds", win._do_save(proj_path) is True)
slots = A.list_backups(proj_path)
with open(slots[0]["path"], encoding="utf-8") as f:
    s1 = len(json.load(f)["servers"])
with open(slots[1]["path"], encoding="utf-8") as f:
    s2 = len(json.load(f)["servers"])
check("after the 3rd save: ring [slot1=3 servers, slot2=2], the newest first",
      len(slots) == 2 and s1 == 3 and s2 == 2, f"slots={[i['slot'] for i in slots]} {s1}/{s2}")

# ══ MainWindow: the autosave on the ticks (ROADMAP #1) ════════════════════════
print("== autosave tick ==")
win.scene.add_server(ServerData(id="a7b5", alias="lb-1", host="127.0.0.1", user="nginx", x=900, y=100))
win._dirty = True
win._autosave_tick()
auto_p = A.autosave_path_for(proj_path)
check("a tick while dirty writes ~/.sshmap/autosave/<key>.json", os.path.isfile(auto_p), auto_p)
auto_data = A.read_autosave(proj_path)
check("the autosave = the current scene (5 servers)",
      auto_data is not None and len(auto_data["servers"]) == 5,
      str(None if auto_data is None else len(auto_data["servers"])))
check("no passwords in the autosave (server_data_to_dict strips them)",
      auto_data is not None and all("password" not in s for s in auto_data["servers"]))

win._dirty = False
app.processEvents()
_mtime_before = os.path.getmtime(auto_p)
win._autosave_tick()
check("a tick while clean does NOT rewrite (dirty only — ROADMAP #1)",
      os.path.getmtime(auto_p) == _mtime_before)

# a new project WITHOUT a file — there is nothing to autosave (ROADMAP #3 is tied to a file)
_auto_files_before = len(os.listdir(A.AUTOSAVE_DIR))
win_ns = MW.MainWindow()
win_ns.scene.add_server(ServerData(id="ns01", alias="orphan", host="127.0.0.1", user="x", x=1, y=1))
win_ns._dirty = True
win_ns._autosave_tick()
_auto_files_after = len(os.listdir(A.AUTOSAVE_DIR))
check("no project file → the autosave tick is a no-op", _auto_files_before == _auto_files_after,
      f"{_auto_files_before} -> {_auto_files_after}")

# ══ The open: the autosave is newer than the file → the offer (ROADMAP #3) ═══════════════
print("== open: autosave newer → prompt ==")
with open(proj_path, encoding="utf-8") as f:
    check("the predicate: the file = 4 servers, the autosave = 5 and newer",
          len(json.load(f)["servers"]) == 4 and A.autosave_is_newer(proj_path))

_q_orig = QMessageBox.question
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
try:
    win2 = MW.MainWindow()
    ok2 = win2._load_project_at(proj_path)
    app.processEvents()
    check("'Yes' → the scene is loaded from the autosave (5 servers)",
          ok2 is True and len(win2.scene.nodes()) == 5, f"nodes={len(win2.scene.nodes())}")
finally:
    QMessageBox.question = _q_orig

QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
try:
    win3 = MW.MainWindow()
    ok3 = win3._load_project_at(proj_path)
    app.processEvents()
    check("'No' → the scene is loaded from the file (4 servers)",
          ok3 is True and len(win3.scene.nodes()) == 4, f"nodes={len(win3.scene.nodes())}")
finally:
    QMessageBox.question = _q_orig

# ══ The backup dialog + the rollback to the previous versions (ROADMAP #2) ════════════════
print("== backups dialog + restore ==")
items = win._backup_items()
check("_backup_items: the autosave + 2 slots, the newest first",
      len(items) == 3
      and items[0]["label"] == it("backups.autosave")
      and items[1]["label"] == it("backups.backup", n=1)
      and items[2]["label"] == it("backups.backup", n=2),
      str([i["label"] for i in items]))

import dialogs.backups_dialog as BD
dlg = BD.BackupsDialog(items, parent=win)
check("BackupsDialog: 3 rows", dlg.item_count() == 3, str(dlg.item_count()))
emitted = []
dlg.restore_requested.connect(lambda p, l: emitted.append((p, l)))
rows = [dlg.tree.topLevelItem(i) for i in range(3)]
dlg.tree.setCurrentItem(rows[2])  # the oldest slot (2 servers)
dlg._emit_restore()
app.processEvents()
check("BackupsDialog emit restore_requested(path, label)",
      emitted == [(items[2]["path"], items[2]["label"])], str(emitted))
dlg.reject()

# the full path: a rollback to slot1 (3 servers) over a dirty project — the "Yes" confirmation
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
try:
    win._restore_from_source(items[1]["path"], items[1]["label"])
    app.processEvents()
    with open(proj_path, encoding="utf-8") as f:
        file_srv = len(json.load(f)["servers"])
    check("a rollback to slot1 → the file and the scene are back to 3 servers",
          file_srv == 3 and len(win.scene.nodes()) == 3,
          f"file={file_srv} nodes={len(win.scene.nodes())}")
    check("after the rollback: dirty is reset (a new undo point)", win._dirty is False)
finally:
    QMessageBox.question = _q_orig

# the "No" confirmation → the project is untouched
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
try:
    nodes_before = len(win.scene.nodes())
    win._restore_from_source(items[2]["path"], items[2]["label"])
    app.processEvents()
    check("the 'No' confirmation → the project is unchanged",
          len(win.scene.nodes()) == nodes_before, f"nodes={len(win.scene.nodes())}")
finally:
    QMessageBox.question = _q_orig

# the manual menu path "Restore from autosave…" (5 servers)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
try:
    win._restore_from_autosave()
    app.processEvents()
    check("the menu 'Restore from Autosave…' → the scene has 5 servers",
          len(win.scene.nodes()) == 5, f"nodes={len(win.scene.nodes())}")
finally:
    QMessageBox.question = _q_orig

# the guard without an open project — an information message, no crash
_info_orig = QMessageBox.information
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
try:
    win_ns._project_file = None
    win_ns._restore_from_autosave()
    win_ns._show_backups_dialog()
    check("no open project → the guard (info), no crash", True)
except Exception as e:  # noqa: BLE001
    check("no open project → the guard (info), no crash", False, repr(e))
finally:
    QMessageBox.information = _info_orig

# ══ i18n: 18 new keys × en/ru/zh ════════════════════════════════════════
print("== i18n ==")
langs = load_i18n_langs(ROOT)
new_keys = ["file.restore_autosave", "file.backups", "dialog.autosave_found",
            "msg.autosave_newer", "dialog.backups", "backups.autosave",
            "backups.backup", "backups.empty", "backups.col_source",
            "backups.col_modified", "backups.col_size", "btn.restore",
            "msg.confirm_restore", "msg.confirm_restore_dirty", "status.restored",
            "status.autosaved", "msg.restore_failed", "msg.open_project_first"]
missing = [k for k in new_keys if any(not langs[c].get(k, "").strip() for c in ("en", "ru", "zh"))]
check("the 18 new v0.9.7 keys are present and non-empty in en/ru/zh", not missing, str(missing))
# v0.9.9.2: +13 external terminal UI keys (ssh_ext.section … ssh_ext.preset.kitty)
# v0.9.9.7: +2 PDF export keys (file.export_pdf, status.export_pdf_ok)
# v1.0RC4: +22 Quick launch keys (ctx.quick_launch … msg.ql_open_failed)
# v1.1: +33 settings dialog keys (settings.* / menu.settings / btn.settings / status.settings_saved)
# v1.1.2RC2: +2 keys (msg.confirm_delete_profile, status.import_resolving)
# v1.1.2 final: +2 keys (settings.statuses.max_parallel, status.auto_interval_hint)
check_i18n_parity(langs)

# Cleanup: first dirty=False — otherwise closeEvent would go to the save dialog.
for w in (win, win2, win3, win_ns):
    try:
        w._dirty = False
        w.close(); w.destroy()
    except Exception:
        pass

# v1.1.2 final (N12): we clean up after ourselves — rmtree of the working folder on EXIT.
# Before, the directory was cut only at the start (line 39) — after every run
# of the suite left _tmp_testdata_v097/app|ring|rt on disk.
shutil.rmtree(WORK, ignore_errors=True)

finish()
