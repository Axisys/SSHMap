"""Save/load проекта headless + keyring-пароли (бывш. smoke_test.py §6 «main window»).

Часть сьюта, разбитого из smoke_test.py v0.6–v0.9.2 (см. INDEX.md).
Критические пункты бывш. AUDIT.md (расшифровка — в CHANGELOG.md): round-trip сохранения/загрузки проекта в offscreen-MainWindow,
[*]-маркер dirty, password → keyring при save (audit #1), key_path в JSON (audit #5),
сброс [*] после save (audit #7), восстановление key_path при загрузке (audit #5),
защита от дублирующихся связей A→B (audit #43).

Запуск: python tests/test_save_load.py   (из корня проекта) или python tests/run_all.py
"""
import json
import os
import sys

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения

from PySide6.QtWidgets import QApplication, QMessageBox
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

# cleanup: при is_available=True выше тест записал тестовые пароли в РЕАЛЬНОЕ
# системное хранилище — удаляем, чтобы прогоны не копили записи «sshmap:snode00N».
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

# duplicate connection protection (audit #43 / docs task 3)
a = win2.scene.add_connection("snode001", "snode002", "l1")
b = win2.scene.add_connection("snode001", "snode002", "dup")
check("duplicate A->B rejected by scene", a is not None and b is None)
check("has_connection detects dup", win2.scene.has_connection("snode001", "snode002"))

finish()
