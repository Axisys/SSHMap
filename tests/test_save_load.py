"""Headless project save/load + keyring passwords (former smoke_test.py §6 "main window").

A part of the suite split out of smoke_test.py v0.6–v0.9.2 (see INDEX.md).
The critical items of the former AUDIT.md (the decoding — in the changelog family): the save/load round-trip of the project in an offscreen MainWindow,
the [*] dirty marker, the password → keyring on save (audit #1), the key_path in the JSON (audit #5),
the [*] reset after the save (audit #7), the key_path restoration on load (audit #5),
the protection against the duplicated A→B connection (audit #43).

Run: python tests/test_save_load.py   (from the project root) or python tests/run_all.py
"""
import json
import os
import sys

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication(sys.argv)

import ui.main_window as MW
from _fakes import QuestionStub
# patch QMessageBox to avoid modal blocking in offscreen mode; record calls
boxes = []

MW.QMessageBox.question = QuestionStub(
    QMessageBox.Save,
    record=lambda title, text: boxes.append(("question", title, text))).install(MW)
MW.QMessageBox.critical = staticmethod(lambda *a, **k: boxes.append(("critical", str(a[1]), str(a[2]))))
MW.QMessageBox.warning = staticmethod(lambda *a, **k: boxes.append(("warning", str(a[1]), str(a[2]))))

from models.server import ServerData, server_data_from_dict
from services.credential_manager import get_credential_manager
cm = get_credential_manager()

print("== main window ==")
win = MW.MainWindow()
check("MainWindow constructed offscreen", win is not None)
check("title has no doubled prefix", win.windowTitle().count("SSH Map") == 1, win.windowTitle())

nd = ServerData(id="snode001", alias="web-1", host="10.0.0.5", user="root",
                password="NodePass999", key_path=r"C:\keys\web.pem", x=10, y=20)
win.scene.add_server(nd)
nd2 = ServerData(id="snode002", alias="db-1", host="10.0.0.6", user="root")
win.scene.add_server(nd2)

# dirty marker
check("not dirty initially", not win._dirty and " [*]" not in win.windowTitle())
win._mark_dirty()
check("_mark_dirty sets title marker", win._dirty and win.windowTitle().endswith("[*]"), win.windowTitle())

path = os.path.join(WORK, "save.json")
ok = win._do_save(path)  # bypasses file dialog
keyring_note = f"keyring_available={cm.is_available}"
check("_do_save returns True", ok is True, keyring_note)
with open(path, encoding="utf-8") as f:
    saved_json = json.load(f)
sids = {s["id"] for s in saved_json["servers"]}
check("saved JSON has both servers", {"snode001", "snode002"} <= sids, str(sids))
s1 = [s for s in saved_json["servers"] if s["id"] == "snode001"][0]
check("saved JSON: password stripped", "password" not in s1 or not s1.get("password"), str(s1.keys()))
check("saved JSON: key_path preserved (audit #5)", s1.get("key_path") == r"C:\keys\web.pem", str(s1))
check("[*] cleared after successful save (audit #7)", not win._dirty and " [*]" not in win.windowTitle(), win.windowTitle())

# password handling with keyring:
if cm.is_available:
    check("password moved to keyring on save", nd.password == "" and cm.load_password("snode001") == "NodePass999")
else:
    w = [b for b in boxes if b[0] == "warning"]
    check("no-keyring: password kept in memory (audit #12)", nd.password == "NodePass999", f"pw={nd.password!r}")
    check("no-keyring warning shown to user", len(w) >= 1, str(boxes))

# cleanup: at is_available=True above the test wrote test passwords into the REAL
# the system store — we remove it so runs do not accumulate "sshmap:snode00N" entries.
if cm.is_available:
    try:
        cm.delete_password("snode001")
        cm.delete_password("snode002")
    except Exception:
        pass

# open project round-trip (audit #5: key_path restored)
win2 = MW.MainWindow()
from storage.project import load_project
raw = load_project(path)
for s in raw["servers"]:
    win2.scene.add_server(server_data_from_dict(s))
loaded1 = win2.scene._nodes.get("snode001")
check("reload: key_path restored via server_data_from_dict", loaded1 is not None and loaded1.data.key_path == r"C:\keys\web.pem")

# v1.6 (ROADMAP task 3): a SECOND link between the same pair is CREATED, not refused in
# silence — the parallel-link offset keeps the two arcs apart (the old check asserted the
# silent refusal, which is exactly the "sometimes it connects, sometimes not" report).
a = win2.scene.add_connection("snode001", "snode002", "l1")
b = win2.scene.add_connection("snode001", "snode002", "dup")
check("a second A->B link is created (and bends aside instead of hiding under the first)",
      a is not None and b is not None and b is not a
      and b.pair_index == 1 and b.offset_px() != 0.0
      and a.path().pointAtPercent(0.5) != b.path().pointAtPercent(0.5),
      f"{a.pair_index} / {b.pair_index}")
check("has_connection detects the pair", win2.scene.has_connection("snode001", "snode002"))

finish()
